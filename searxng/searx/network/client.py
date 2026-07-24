# SPDX-License-Identifier: AGPL-3.0-or-later
# pylint: disable=missing-module-docstring, global-statement

import typing as t
from types import TracebackType

import asyncio
import logging
import random
from ssl import SSLContext
import threading

import httpx
from httpx_socks import AsyncProxyTransport
from python_socks import parse_proxy_url, ProxyConnectionError, ProxyTimeoutError, ProxyError

from searx import logger

# TLS fingerprint impersonation via curl_cffi (optional)
try:
    from curl_cffi.requests import AsyncSession as CurlCffiAsyncSession
    CURL_CFFI_AVAILABLE = True
except ImportError:
    CURL_CFFI_AVAILABLE = False

CertTypes = str | tuple[str, str] | tuple[str, str, str]
SslContextKeyType = tuple[str | None, CertTypes | None, bool, bool]

logger = logger.getChild('searx.network.client')
LOOP: asyncio.AbstractEventLoop = None  # pyright: ignore[reportAssignmentType]

SSLCONTEXTS: dict[SslContextKeyType, SSLContext] = {}


def shuffle_ciphers(ssl_context: SSLContext):
    """Shuffle httpx's default ciphers of a SSL context randomly.

    From `What Is TLS Fingerprint and How to Bypass It`_

    > When implementing TLS fingerprinting, servers can't operate based on a
    > locked-in whitelist database of fingerprints.  New fingerprints appear
    > when web clients or TLS libraries release new versions. So, they have to
    > live off a blocklist database instead.
    > ...
    > It's safe to leave the first three as is but shuffle the remaining ciphers
    > and you can bypass the TLS fingerprint check.

    .. _What Is TLS Fingerprint and How to Bypass It:
       https://www.zenrows.com/blog/what-is-tls-fingerprint#how-to-bypass-tls-fingerprinting

    """
    c_list = [cipher["name"] for cipher in ssl_context.get_ciphers()]
    sc_list, c_list = c_list[:3], c_list[3:]
    random.shuffle(c_list)
    ssl_context.set_ciphers(":".join(sc_list + c_list))


class CurlCffiTransport:
    """httpx-compatible transport using curl_cffi for TLS fingerprint impersonation.
    
    This allows SearXNG to match real browser JA3/JA4 fingerprints
    (chrome120, firefox121, safari17_2_ios, edge101, etc.) instead of
    httpx's default fingerprint which is easily detected by Cloudflare,
    Akamai, and other bot protection.
    """
    
    def __init__(
        self,
        impersonate: str = "chrome120",
        proxy: str | None = None,
        verify: bool = True,
        http2: bool = True,
        local_address: str | None = None,
        limits: httpx.Limits | None = None,
        retries: int = 0,
    ):
        if not CURL_CFFI_AVAILABLE:
            raise RuntimeError("curl_cffi not installed. Run: pip install curl_cffi")
        
        self._impersonate = impersonate
        self._proxy = proxy
        self._verify = verify
        self._http2 = http2
        self._local_address = local_address
        self._limits = limits
        self._retries = retries
        self._session: CurlCffiAsyncSession | None = None
        
    async def _get_session(self) -> CurlCffiAsyncSession:
        if self._session is None:
            # curl_cffi AsyncSession accepts proxy, verify, timeout in constructor
            # impersonate is set per-request
            self._session = CurlCffiAsyncSession(
                proxy=self._proxy,
                verify=self._verify,
                timeout=30.0,
                max_clients=10,
            )
        return self._session
    
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        session = await self._get_session()
        
        # Prepare request
        headers = dict(request.headers)
        # Disable compression to avoid double-decode issues with httpx
        headers["Accept-Encoding"] = "identity"
        method = request.method
        url = str(request.url)
        content = request.content
        
        # Make request via curl_cffi with impersonation
        resp = await session.request(
            method=method,
            url=url,
            headers=headers,
            data=content,
            allow_redirects=True,
            impersonate=self._impersonate,
        )
        
        # Convert to httpx.Response
        # Remove ALL Content-Encoding variants since curl_cffi already decompressed
        resp_headers = dict(resp.headers)
        for key in list(resp_headers.keys()):
            if key.lower() == "content-encoding":
                resp_headers.pop(key, None)
        # Also remove Transfer-Encoding as curl_cffi handles chunked transfer
        for key in list(resp_headers.keys()):
            if key.lower() == "transfer-encoding":
                resp_headers.pop(key, None)
        
        return httpx.Response(
            status_code=resp.status_code,
            headers=resp_headers,
            content=resp.content,
            request=request,
        )
    
    async def aclose(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        await self.aclose()


def get_sslcontexts(
    proxy_url: str | None = None, cert: CertTypes | None = None, verify: bool = True, trust_env: bool = True
) -> SSLContext:
    key: SslContextKeyType = (proxy_url, cert, verify, trust_env)
    if key not in SSLCONTEXTS:
        SSLCONTEXTS[key] = httpx.create_ssl_context(verify, cert, trust_env)
    shuffle_ciphers(SSLCONTEXTS[key])
    return SSLCONTEXTS[key]


class AsyncHTTPTransportNoHttp(httpx.AsyncHTTPTransport):
    """Block HTTP request

    The constructor is blank because httpx.AsyncHTTPTransport.__init__ creates an SSLContext unconditionally:
    https://github.com/encode/httpx/blob/0f61aa58d66680c239ce43c8cdd453e7dc532bfc/httpx/_transports/default.py#L271

    Each SSLContext consumes more than 500kb of memory, since there is about one network per engine.

    In consequence, this class overrides all public methods

    For reference: https://github.com/encode/httpx/issues/2298
    """

    def __init__(self, *args, **kwargs):  # type: ignore
        # pylint: disable=super-init-not-called
        # this on purpose if the base class is not called
        pass

    async def handle_async_request(self, request: httpx.Request):
        raise httpx.UnsupportedProtocol('HTTP protocol is disabled')

    async def aclose(self) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        pass


class AsyncProxyTransportFixed(AsyncProxyTransport):
    """Fix httpx_socks.AsyncProxyTransport

    Map python_socks exceptions to httpx.ProxyError exceptions
    """

    async def handle_async_request(self, request: httpx.Request):
        try:
            return await super().handle_async_request(request)
        except ProxyConnectionError as e:
            raise httpx.ProxyError("ProxyConnectionError: " + str(e.strerror), request=request) from e
        except ProxyTimeoutError as e:
            raise httpx.ProxyError("ProxyTimeoutError: " + str(e.args[0]), request=request) from e
        except ProxyError as e:
            raise httpx.ProxyError("ProxyError: " + str(e.args[0]), request=request) from e


def get_transport_for_socks_proxy(
    verify: bool, http2: bool, local_address: str, proxy_url: str, limit: httpx.Limits, retries: int,
    impersonate: str | None = None,
):
    # support socks5h (requests compatibility):
    # https://requests.readthedocs.io/en/master/user/advanced/#socks
    # socks5://   hostname is resolved on client side
    # socks5h://  hostname is resolved on proxy side
    rdns = False
    socks5h = 'socks5h://'
    if proxy_url.startswith(socks5h):
        proxy_url = 'socks5://' + proxy_url[len(socks5h) :]
        rdns = True

    proxy_type, proxy_host, proxy_port, proxy_username, proxy_password = parse_proxy_url(proxy_url)
    _verify = get_sslcontexts(proxy_url, None, verify, True) if verify is True else verify
    
    # Note: curl_cffi impersonation doesn't directly work with SOCKS proxies via httpx_socks.
    # For impersonation with proxies, use HTTP/HTTPS proxies instead.
    return AsyncProxyTransportFixed(
        proxy_type=proxy_type,
        proxy_host=proxy_host,
        proxy_port=proxy_port,
        username=proxy_username,
        password=proxy_password,
        rdns=rdns,
        loop=get_loop(),
        verify=_verify,  # pyright: ignore[reportArgumentType]
        http2=http2,
        local_address=local_address,
        limits=limit,
        retries=retries,
    )


def get_transport(
    verify: bool, http2: bool, local_address: str, proxy_url: str | None, limit: httpx.Limits, retries: int,
    impersonate: str | None = None,
):
    # Use curl_cffi transport for TLS fingerprint impersonation
    if impersonate and CURL_CFFI_AVAILABLE:
        return CurlCffiTransport(
            impersonate=impersonate,
            proxy=proxy_url,
            verify=verify,
            http2=http2,
            local_address=local_address,
            limits=limit,
            retries=retries,
        )
    
    _verify = get_sslcontexts(None, None, verify, True) if verify is True else verify
    return httpx.AsyncHTTPTransport(
        # pylint: disable=protected-access
        verify=_verify,
        http2=http2,
        limits=limit,
        proxy=httpx._config.Proxy(proxy_url) if proxy_url else None,  # pyright: ignore[reportPrivateUsage]
        local_address=local_address,
        retries=retries,
    )


def new_client(
    # pylint: disable=too-many-arguments
    enable_http: bool,
    verify: bool,
    enable_http2: bool,
    max_connections: int,
    max_keepalive_connections: int,
    keepalive_expiry: float,
    proxies: dict[str, str],
    local_address: str,
    retries: int,
    max_redirects: int,
    hook_log_response: t.Callable[..., t.Any] | None,
    impersonate: str | None = None,
) -> httpx.AsyncClient:
    limit = httpx.Limits(
        max_connections=max_connections,
        max_keepalive_connections=max_keepalive_connections,
        keepalive_expiry=keepalive_expiry,
    )
    # See https://www.python-httpx.org/advanced/#routing
    mounts = {}
    mounts: None | (dict[str, t.Any | None]) = {}
    for pattern, proxy_url in proxies.items():
        if not enable_http and pattern.startswith('http://'):
            continue
        if proxy_url.startswith('socks4://') or proxy_url.startswith('socks5://') or proxy_url.startswith('socks5h://'):
            mounts[pattern] = get_transport_for_socks_proxy(
                verify, enable_http2, local_address, proxy_url, limit, retries
            )
        else:
            mounts[pattern] = get_transport(verify, enable_http2, local_address, proxy_url, limit, retries, impersonate)

    if not enable_http:
        mounts['http://'] = AsyncHTTPTransportNoHttp()

    transport = get_transport(verify, enable_http2, local_address, None, limit, retries, impersonate)

    event_hooks = None
    if hook_log_response:
        event_hooks = {'response': [hook_log_response]}

    return httpx.AsyncClient(
        transport=transport,
        mounts=mounts,
        max_redirects=max_redirects,
        event_hooks=event_hooks,
    )


def get_loop() -> asyncio.AbstractEventLoop:
    return LOOP


def init():
    # log
    for logger_name in (
        'httpx',
        'httpcore.proxy',
        'httpcore.connection',
        'httpcore.http11',
        'httpcore.http2',
        'hpack.hpack',
        'hpack.table',
    ):
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    # loop
    def loop_thread():
        global LOOP
        LOOP = asyncio.new_event_loop()
        LOOP.run_forever()

    thread = threading.Thread(
        target=loop_thread,
        name='asyncio_loop',
        daemon=True,
    )
    thread.start()


init()
