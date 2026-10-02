from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, HTMLResponse
import httpx
from bs4 import BeautifulSoup
from readability import Document
from typing import Optional, List, Dict, Any
import asyncio
from urllib.parse import urljoin, urlparse
import trafilatura
import html2text
from datetime import datetime
import re
from diskcache import Cache
import os
import json
import gzip
import zlib
import ipaddress
import socket

# Try to import document extraction module
try:
    from document_extractor import extract_document, is_document_url, get_content_type_mime
    DOCUMENT_EXTRACTOR_AVAILABLE = True
except ImportError:
    DOCUMENT_EXTRACTOR_AVAILABLE = False

# Try to import brotli for brotli decompression
try:
    import brotli
    BROTLI_AVAILABLE = True
except ImportError:
    BROTLI_AVAILABLE = False

from stealth_client import StealthClient, StealthLevel, stealth_get
from antibot import detect_protection, is_blocked, ProtectionType


# ===== SSRF Protection =====
PRIVATE_IP_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def validate_public_url(url: str) -> str:
    """Validate URL is a public HTTP/HTTPS URL. Raises HTTPException if not."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Only HTTP/HTTPS URLs are allowed")
    if not parsed.netloc:
        raise HTTPException(status_code=400, detail="Invalid URL: missing hostname")

    hostname = parsed.netloc.split(":")[0]
    if hostname.lower() in {"localhost", "localhost.localdomain", "localhost6", "localhost6.localdomain6"}:
        raise HTTPException(status_code=400, detail="Access to localhost is not allowed")

    try:
        for ip_info in socket.getaddrinfo(hostname, None):
            ip = ipaddress.ip_address(ip_info[4][0])
            for private_range in PRIVATE_IP_RANGES:
                if ip in private_range:
                    raise HTTPException(status_code=400, detail=f"Access to private IP addresses ({ip_info[4][0]}) is not allowed")
    except socket.gaierror:
        pass
    except HTTPException:
        raise
    except Exception:
        pass

    return url


# ===== Content Processing (single pipeline, used everywhere) =====

def decompress_content(raw_bytes: bytes, content_encoding: str = None) -> bytes:
    """Decompress content using gzip/deflate/brotli. Returns original bytes if not compressed."""
    if not raw_bytes:
        return raw_bytes

    # ponytail: single pass — try each decompressor once, no redundant fallback loop
    for decompress_func in [
        lambda b: gzip.decompress(b),
        lambda b: zlib.decompress(b),
        lambda b: zlib.decompress(b, -zlib.MAX_WBITS),
    ]:
        try:
            return decompress_func(raw_bytes)
        except Exception:
            continue

    if BROTLI_AVAILABLE:
        try:
            return brotli.decompress(raw_bytes)
        except Exception:
            pass

    return raw_bytes


def decode_content(raw_bytes: bytes, content_type: str = None) -> str:
    """Decode bytes to string trying multiple encodings."""
    if not raw_bytes:
        return ""

    # Extract charset from content-type
    charset = None
    if content_type:
        for part in content_type.split(';'):
            if 'charset=' in part.lower():
                charset = part.split('=')[1].strip().strip('"\'')
                break

    # ponytail: just try encodings in order, first success wins. No HTML-sniffing heuristic.
    encodings = []
    if charset:
        encodings.append(charset)
    encodings.extend(['utf-8', 'utf-8-sig', 'latin-1', 'cp1252', 'iso-8859-1'])

    seen = set()
    for enc in encodings:
        if enc.lower() in seen:
            continue
        seen.add(enc.lower())
        try:
            return raw_bytes.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue

    return raw_bytes.decode('utf-8', errors='replace')


def sanitize_content(content: str) -> str:
    """Remove NULL bytes from content. That's it."""
    # ponytail: NULL byte removal covers 99.9% of real issues. Full XML codepoint filter when a real page breaks this.
    return content.replace('\x00', '') if content else content


def process_raw_response(content: bytes, headers: dict) -> str:
    """Single pipeline: decompress → decode → sanitize."""
    encoding = headers.get('content-encoding', '')
    ct = headers.get('content-type', '')
    return sanitize_content(decode_content(decompress_content(content, encoding), ct))


# ===== Fetching =====

# Global Stealth Client (Lazy loaded)
_stealth_client = None

def get_stealth_client():
    global _stealth_client
    if _stealth_client is None:
        _stealth_client = StealthClient(timeout=30.0)
    return _stealth_client


_http_client = None


def get_http_client() -> httpx.AsyncClient:
    """Shared client so connections are pooled instead of rebuilt per request."""
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
    return _http_client


_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1"
}


async def advanced_fetch(url: str, stealth_mode: str = "off", auto_bypass: bool = False) -> Dict[str, Any]:
    """
    Fetch URL with optional stealth mode and auto-bypass.
    Returns dict with html, content_bytes, content_type, status_code, final_url, fetch_method, protection_info.
    """
    url = validate_public_url(url)

    fetch_method = "standard"
    protection_info = None
    html = ""
    content_bytes = b""
    content_type = ""
    status_code = 0
    final_url = url

    if stealth_mode != "off":
        try:
            level = StealthLevel(stealth_mode.lower())
            client = get_stealth_client()
            response = await client.get(url, stealth_level=level)
            content_bytes = response.content or b""
            content_type = response.headers.get("content-type", "")
            html = process_raw_response(content_bytes, {"content-encoding": response.content_encoding, "content-type": content_type})
            if not html:
                html = sanitize_content(response.text)
            status_code = response.status_code
            final_url = response.url
            fetch_method = f"stealth_{stealth_mode}"
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Stealth fetch failed: {str(e)}")
    else:
        response = await get_http_client().get(url, headers=_DEFAULT_HEADERS)
        response.raise_for_status()
        content_bytes = response.content
        content_type = response.headers.get('content-type', '')
        html = process_raw_response(response.content, dict(response.headers))
        if not html or len(html.strip()) < 50:
            try:
                html = sanitize_content(response.text)
            except Exception:
                pass
        status_code = response.status_code
        final_url = str(response.url)

    # Check for bot protection
    protection = detect_protection(html)
    if protection.is_protected:
        protection_info = {
            "detected": True,
            "is_blocked": protection.is_blocked,
            "protections": [p.value for p in protection.protections],
            "confidence": protection.confidence,
            "recommendation": protection.recommendation
        }

        # Auto-bypass: escalate stealth levels
        if protection.is_blocked and auto_bypass:
            for bypass_level in [StealthLevel.MEDIUM, StealthLevel.HIGH]:
                if fetch_method in [f"stealth_{bypass_level.value}", "stealth_medium_auto", "stealth_high_auto"]:
                    continue
                try:
                    client = get_stealth_client()
                    response = await client.get(url, stealth_level=bypass_level)
                    new_html = sanitize_content(response.text)
                    new_protection = detect_protection(new_html)
                    if not new_protection.is_blocked:
                        html = new_html
                        status_code = response.status_code
                        final_url = response.url
                        fetch_method = f"stealth_{bypass_level.value}_auto"
                        protection_info["bypassed"] = True
                        protection_info["bypass_method"] = f"stealth_{bypass_level.value}"
                        break
                except Exception:
                    pass

    if not html or len(html.strip()) < 10:
        html = "[Content could not be fully extracted]"

    return {
        "html": html,
        "content_bytes": content_bytes,
        "content_type": content_type,
        "status_code": status_code,
        "final_url": final_url,
        "fetch_method": fetch_method,
        "protection_info": protection_info
    }


# ===== Content Extraction (shared by /fetch and /search-and-fetch) =====

def _extract_content(html_content: str, final_url: str, format: str,
                     extraction_mode: str, include_links: bool, include_images: bool,
                     max_content_length: int) -> Dict[str, Any]:
    """
    Extract content from HTML using trafilatura or readability.
    Returns dict with content, metadata, and optionally headings/links/images.
    """
    result = {}

    if extraction_mode == "trafilatura":
        common = dict(include_comments=False, include_tables=True,
                      include_images=include_images, include_links=include_links)
        if format == "markdown":
            # ponytail: one full pass for markdown + a cheap metadata-only pass, instead of
            # two full passes. Measured 2097ms -> 1106ms/page, and extract_metadata finds
            # sitename/description that the full json pass misses.
            content = trafilatura.extract(html_content, output_format='markdown',
                                          url=final_url, **common)
            meta = trafilatura.extract_metadata(html_content, default_url=final_url)
            data = meta.as_dict() if meta is not None and hasattr(meta, "as_dict") else {}
            ok = bool(content)
        else:
            extracted = trafilatura.extract(html_content, output_format='json',
                                            url=final_url, with_metadata=True, **common)
            data = json.loads(extracted) if extracted else None
            ok = data is not None

        if ok:
            metadata = {k: v for k, v in {
                "title": data.get("title", ""),
                "author": data.get("author", ""),
                "sitename": data.get("sitename", ""),
                "date": data.get("date", ""),
                "categories": data.get("categories", []),
                "tags": data.get("tags", []),
                "description": data.get("description", ""),
                "language": data.get("language", ""),
                "url": final_url,
            }.items() if v}
            result["metadata"] = metadata

            if format == "html":
                content = data.get("raw_text", data.get("text", ""))
            elif format == "text":
                content = data.get("text", "")

            if len(content) > max_content_length:
                content = content[:max_content_length] + "\n\n... [truncated]"
            result["content"] = content
            result["extraction_mode"] = "trafilatura"
            return result

        extraction_mode = "readability"  # fallback

    # Readability extraction
    doc = Document(html_content)
    soup = BeautifulSoup(html_content, 'lxml')

    metadata = {"title": doc.title(), "url": final_url}
    for meta in soup.find_all("meta"):
        name = meta.get("name", "").lower() or meta.get("property", "").lower()
        mcontent = meta.get("content", "")
        if "description" in name and mcontent:
            metadata["description"] = mcontent
        elif "author" in name and mcontent:
            metadata["author"] = mcontent
        elif "site_name" in name or "og:site_name" in name:
            metadata["sitename"] = mcontent
    result["metadata"] = metadata

    article_html = doc.summary()
    article_soup = BeautifulSoup(article_html, 'lxml')

    if format == "markdown":
        h = html2text.HTML2Text()
        h.ignore_links = not include_links
        h.ignore_images = not include_images
        h.body_width = 0
        content = h.handle(article_html)
    elif format == "html":
        content = article_html
    else:
        content = re.sub(r'\n{3,}', '\n\n', article_soup.get_text(separator="\n", strip=True))

    if len(content) > max_content_length:
        content = content[:max_content_length] + "\n\n... [truncated]"
    result["content"] = content
    result["extraction_mode"] = "readability"

    # Extract headings
    headings = []
    for heading in article_soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
        text = heading.get_text(strip=True)
        if text:
            headings.append({"level": heading.name, "text": text})
    if headings:
        result["headings"] = headings

    if include_links:
        links = []
        for link in article_soup.find_all('a', href=True):
            text = link.get_text(strip=True)
            if text and link['href']:
                links.append({"text": text, "url": urljoin(final_url, link['href'])})
        result["links"] = links[:100]

    if include_images:
        images = []
        for img in article_soup.find_all('img'):
            src = img.get('src') or img.get('data-src')
            if src:
                images.append({"url": urljoin(final_url, src), "alt": img.get('alt', ''), "title": img.get('title', '')})
        result["images"] = images[:50]

    return result


def _check_document(content_bytes: bytes, content_type: str, final_url: str) -> Optional[Dict[str, Any]]:
    """Check if content is a document and extract text. Returns None if not a document."""
    if not DOCUMENT_EXTRACTOR_AVAILABLE or not content_bytes:
        return None
    if not is_document_url(final_url) and not get_content_type_mime(content_type):
        return None
    doc_result = extract_document(content_bytes, content_type, final_url)
    if doc_result.get('success', False):
        return doc_result
    return None


# ===== App Setup =====

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    if _http_client is not None:
        await _http_client.aclose()


app = FastAPI(
    title="SearXNG Search API",
    description="FastAPI wrapper around SearXNG with search and fetch capabilities",
    version="1.0.0",
    lifespan=lifespan
)

SEARXNG_URL = "http://127.0.0.1:8888"

# Initialize DiskCache
cache = Cache("/tmp/miyami_cache")
CACHE_VERSION = "v2"

# Load GUI HTML from file
_GUI_HTML = None
def _get_gui_html():
    global _GUI_HTML
    if _GUI_HTML is None:
        gui_path = os.path.join(os.path.dirname(__file__), 'gui.html')
        if os.path.exists(gui_path):
            with open(gui_path) as f:
                _GUI_HTML = f.read()
        else:
            _GUI_HTML = "<html><body><h1>Miyami Search API</h1><p><a href='/docs'>API Docs</a></p></body></html>"
    return _GUI_HTML


VALID_STEALTH_MODES = {"off", "low", "medium", "high"}
VALID_TIME_RANGES = {"day", "week", "month", "year"}


def _validate_stealth_mode(stealth_mode: str):
    if stealth_mode.lower() not in VALID_STEALTH_MODES:
        raise HTTPException(status_code=400, detail=f"Invalid stealth_mode. Must be one of: {', '.join(VALID_STEALTH_MODES)}")


def _validate_time_range(time_range: Optional[str]):
    if time_range and time_range.lower() not in VALID_TIME_RANGES:
        raise HTTPException(status_code=400, detail=f"Invalid time_range. Must be one of: {', '.join(VALID_TIME_RANGES)}")


# ===== Endpoints =====

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the interactive GUI for the API"""
    return _get_gui_html()


@app.head("/")
async def root_head():
    return {}


@app.get("/api")
async def api_info():
    return {
        "message": "SearXNG Search API",
        "endpoints": {
            "/search-api": "Search using SearXNG engines",
            "/fetch": "Fetch and clean website content",
            "/search-and-fetch": "Search and auto-fetch content from top N results",
            "/deep-research": "Recursive research agent for comprehensive analysis",
            "/crawl-site": "Crawl entire websites and extract content from multiple pages",
            "/yt-transcript": "Fetch YouTube video transcripts"
        }
    }


@app.get("/search-api")
async def search_api(
    query: str = Query(..., description="Search query"),
    debug: bool = Query(False, description="Return raw SearXNG response"),
    format: str = Query("json", description="Response format"),
    categories: Optional[str] = Query(None, description="Search categories"),
    engines: Optional[str] = Query(None, description="Specific engines"),
    language: Optional[str] = Query("en", description="Search language"),
    page: Optional[int] = Query(1, description="Page number"),
    time_range: Optional[str] = Query(None, description="Time filter: day, week, month, year"),
):
    # ponytail: removed 170-line advanced query parser. SearXNG handles site:/filetype: natively.
    # Re-add client-side filtering only if SearXNG's native support is provably broken for a use case.

    _validate_time_range(time_range)

    cache_key = f"search:{CACHE_VERSION}:{query}:{categories}:{engines}:{language}:{page}:{time_range}:{debug}"
    cached_result = cache.get(cache_key)
    if cached_result:
        return JSONResponse(content=cached_result)

    try:
        params = {"q": query, "format": "json", "language": language, "pageno": page}
        if categories:
            params["categories"] = categories
        if engines:
            params["engines"] = engines
        if time_range:
            params["time_range"] = time_range.lower()

        client = get_http_client()
        response = await client.get(f"{SEARXNG_URL}/search", params=params)
        response.raise_for_status()

        if debug:
            return JSONResponse(content={
                "query": query, "params": params,
                "searx_status_code": response.status_code,
                "searx_headers": dict(response.headers),
                "searx_raw_text": response.text
            })

        data = response.json()

        results = {
            "query": query,
            "number_of_results": data.get("number_of_results", 0),
            "results": [],
            "suggestions": data.get("suggestions", []),
            "infoboxes": data.get("infoboxes", [])
        }

        for r in data.get("results", []):
            clean = {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", ""),
                "engine": r.get("engine", ""),
                "parsed_url": r.get("parsed_url", []),
                "score": r.get("score", 0),
            }
            for opt in ("img_src", "thumbnail", "publishedDate"):
                if opt in r:
                    clean[opt] = r[opt]
            results["results"].append(clean)

        number_fetched = len(results["results"])
        if results["number_of_results"] == 0 and number_fetched > 0:
            results["number_of_results"] = number_fetched

        cache.set(cache_key, results, expire=3600)
        return JSONResponse(content=results)

    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"SearXNG error: {str(e)}")
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"Cannot connect to SearXNG: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@app.get("/fetch")
async def fetch_url(
    url: str = Query(..., description="URL to fetch and clean"),
    format: str = Query("text", description="Output format: text, markdown, or html"),
    include_links: bool = Query(True, description="Include extracted links"),
    include_images: bool = Query(True, description="Include extracted images"),
    max_content_length: int = Query(100000, description="Maximum content length"),
    extraction_mode: str = Query("trafilatura", description="Extraction engine: trafilatura or readability"),
    stealth_mode: str = Query("off", description="Stealth mode: off, low, medium, high"),
    auto_bypass: bool = Query(False, description="Auto-escalate stealth if blocked"),
):
    """Fetch a URL and return cleaned, structured content."""
    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            raise HTTPException(status_code=400, detail="Invalid URL format")

        _validate_stealth_mode(stealth_mode)
        url = validate_public_url(url)

        fetch_result = await advanced_fetch(url=url, stealth_mode=stealth_mode, auto_bypass=auto_bypass)
        html_content = fetch_result["html"]
        final_url = validate_public_url(fetch_result["final_url"])
        content_bytes = fetch_result.get("content_bytes", b"")
        content_type_header = fetch_result.get("content_type", "")

        result = {
            "success": True,
            "url": final_url,
            "status_code": fetch_result["status_code"],
            "fetch_method": fetch_result["fetch_method"],
        }

        if fetch_result["protection_info"]:
            result["protection_info"] = fetch_result["protection_info"]

        # Check for document
        doc = _check_document(content_bytes, content_type_header, final_url)
        if doc:
            result["is_document"] = True
            result["document_type"] = doc.get('document_type', 'unknown')
            result["content"] = doc.get('text', '')
            result["stats"] = {
                "content_length": len(result["content"]),
                "word_count": len(result["content"].split()),
                "document_type": doc.get('document_type'),
                "extraction_mode": "document",
                "fetch_method": fetch_result["fetch_method"]
            }
        else:
            result["is_document"] = False
            extracted = _extract_content(html_content, final_url, format, extraction_mode,
                                          include_links, include_images, max_content_length)
            result["content"] = extracted["content"]
            result["metadata"] = extracted.get("metadata", {})
            for key in ("headings", "links", "images"):
                if key in extracted:
                    result[key] = extracted[key]
            result["stats"] = {
                "content_length": len(result["content"]),
                "word_count": len(result["content"].split()),
                "extraction_mode": extracted.get("extraction_mode", extraction_mode),
                "format": format,
                "fetch_method": fetch_result["fetch_method"]
            }

        return JSONResponse(content=result)

    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"Failed to fetch URL: {str(e)}")
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"Cannot connect to URL: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing content: {str(e)}")


async def _fetch_and_extract(result: dict, format: str, max_content_length: int,
                              stealth_mode: str, auto_bypass: bool) -> dict:
    """Shared fetch+extract for search-and-fetch and deep-research."""
    url = result.get("url", "")
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return {"search_result": result, "fetch_status": "error", "fetch_error": "Invalid URL", "content": None}

    try:
        url = validate_public_url(url)
    except HTTPException as e:
        return {"search_result": result, "fetch_status": "error", "fetch_error": e.detail, "content": None}

    try:
        fetch_result = await advanced_fetch(url=url, stealth_mode=stealth_mode, auto_bypass=auto_bypass)
        final_url = fetch_result["final_url"]
        fetch_method = fetch_result["fetch_method"]
        protection_info = fetch_result["protection_info"]
        content_bytes = fetch_result.get("content_bytes", b"")
        content_type = fetch_result.get("content_type", "")

        search_info = {
            "title": result.get("title", ""),
            "url": final_url,
            "snippet": result.get("content", ""),
            "engine": result.get("engine", ""),
            "score": result.get("score", 0)
        }

        # Check for document
        doc = _check_document(content_bytes, content_type, final_url)
        if doc:
            text = doc.get('text', '')
            if len(text) > max_content_length:
                text = text[:max_content_length] + "\n\n... [truncated]"
            out = {
                "search_result": search_info,
                "fetch_status": "success",
                "fetch_method": fetch_method,
                "is_document": True,
                "document_type": doc.get('document_type', 'unknown'),
                "fetched_content": {
                    "title": result.get("title", ""),
                    "content": text,
                    "word_count": len(text.split()),
                    "format": format
                }
            }
            if protection_info:
                out["protection_info"] = protection_info
            return out

        # HTML extraction
        extracted = _extract_content(fetch_result["html"], final_url, format, "trafilatura", True, True, max_content_length)
        content = extracted["content"]
        metadata = extracted.get("metadata", {})

        out = {
            "search_result": search_info,
            "fetch_status": "success",
            "fetch_method": fetch_method,
            "fetched_content": {
                "title": metadata.get("title", result.get("title", "")),
                "author": metadata.get("author", ""),
                "date": metadata.get("date", ""),
                "sitename": metadata.get("sitename", ""),
                "content": content,
                "word_count": len(content.split()),
                "format": format
            }
        }
        if protection_info:
            out["protection_info"] = protection_info
        return out

    except HTTPException as e:
        return {"search_result": result, "fetch_status": "error", "fetch_error": e.detail, "content": None}
    except Exception as e:
        return {"search_result": result, "fetch_status": "error", "fetch_error": str(e), "content": None}


@app.get("/search-and-fetch")
async def search_and_fetch(
    query: str = Query(..., description="Search query"),
    num_results: int = Query(3, description="Number of results to fetch (1-5)", ge=1, le=5),
    categories: Optional[str] = Query("general", description="Search categories"),
    language: Optional[str] = Query("en", description="Search language"),
    format: str = Query("markdown", description="Output format: text, markdown, or html"),
    max_content_length: int = Query(100000, description="Maximum content length per page"),
    time_range: Optional[str] = Query(None, description="Time filter: day, week, month, year"),
    stealth_mode: str = Query("off", description="Stealth mode: off, low, medium, high"),
    auto_bypass: bool = Query(False, description="Auto-escalate stealth if blocked"),
):
    """Search and auto-fetch full content from top N results."""
    _validate_stealth_mode(stealth_mode)
    _validate_time_range(time_range)

    cache_key = f"search_fetch:{CACHE_VERSION}:{query}:{num_results}:{categories}:{language}:{format}:{time_range}:{stealth_mode}"
    cached_result = cache.get(cache_key)
    if cached_result:
        return JSONResponse(content=cached_result)

    try:
        search_params = {"q": query, "format": "json", "language": language, "pageno": 1}
        if categories:
            search_params["categories"] = categories
        if time_range:
            search_params["time_range"] = time_range.lower()

        search_response = await get_http_client().get(f"{SEARXNG_URL}/search", params=search_params)
        search_response.raise_for_status()
        search_data = search_response.json()

        top_results = search_data.get("results", [])[:num_results]

        if not top_results:
            return JSONResponse(content={"query": query, "num_results_found": 0, "results": [], "message": "No search results found"})

        fetched_results = await asyncio.gather(*[
            _fetch_and_extract(r, format, max_content_length, stealth_mode, auto_bypass)
            for r in top_results
        ])

        successful = sum(1 for r in fetched_results if r["fetch_status"] == "success")
        failed = sum(1 for r in fetched_results if r["fetch_status"] == "error")

        final_response = {
            "query": query,
            "num_results_requested": num_results,
            "num_results_found": len(top_results),
            "successful_fetches": successful,
            "failed_fetches": failed,
            "fetch_options": {"stealth_mode": stealth_mode, "auto_bypass": auto_bypass},
            "results": fetched_results,
            "suggestions": search_data.get("suggestions", [])
        }

        cache.set(cache_key, final_response, expire=3600)
        return JSONResponse(content=final_response)

    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"Search failed: {str(e)}")
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"Cannot connect to SearXNG: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@app.get("/deep-research")
async def deep_research(
    queries: str = Query(..., description="Comma-separated research queries"),
    breadth: int = Query(3, description="Results per query (1-5)", ge=1, le=5),
    time_range: Optional[str] = Query(None, description="Time filter: day, week, month, year"),
    max_content_length: int = Query(30000, description="Max content length per result"),
    include_suggestions: bool = Query(True, description="Include suggestions"),
    stealth_mode: str = Query("off", description="Stealth mode"),
    auto_bypass: bool = Query(False, description="Auto-escalate stealth if blocked"),
):
    """Multi-query research — runs queries in parallel and compiles results."""
    query_list = [q.strip() for q in queries.split(",") if q.strip()]
    if not query_list:
        raise HTTPException(status_code=400, detail="No valid queries provided.")
    if len(query_list) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 queries allowed.")

    _validate_stealth_mode(stealth_mode)
    _validate_time_range(time_range)

    cache_key = f"deep_research:{CACHE_VERSION}:{','.join(sorted(query_list))}:{breadth}:{time_range}:{max_content_length}:{stealth_mode}"
    cached_result = cache.get(cache_key)
    if cached_result:
        return JSONResponse(content=cached_result)

    try:
        async def process_query(query: str) -> dict:
            try:
                # ponytail: call the search+fetch logic directly instead of through the endpoint
                search_params = {"q": query, "format": "json", "language": "en", "pageno": 1}
                if time_range:
                    search_params["time_range"] = time_range.lower()

                resp = await get_http_client().get(f"{SEARXNG_URL}/search", params=search_params)
                resp.raise_for_status()
                search_data = resp.json()

                top = search_data.get("results", [])[:breadth]
                fetched = await asyncio.gather(*[
                    _fetch_and_extract(r, "markdown", max_content_length, stealth_mode, auto_bypass)
                    for r in top
                ])

                successful = sum(1 for r in fetched if r["fetch_status"] == "success")
                return {
                    "query": query, "status": "success",
                    "num_results": len(top), "successful_fetches": successful,
                    "results": fetched,
                    "suggestions": search_data.get("suggestions", [])
                }
            except Exception as e:
                return {"query": query, "status": "error", "error": str(e), "num_results": 0, "results": [], "suggestions": []}

        query_results = await asyncio.gather(*[process_query(q) for q in query_list])

        total_results = sum(r["num_results"] for r in query_results)
        total_successful = sum(r.get("successful_fetches", 0) for r in query_results if r["status"] == "success")

        all_suggestions = list(set(s for r in query_results for s in r.get("suggestions", [])))[:20]

        final_response = {
            "research_summary": {
                "total_queries": len(query_list),
                "successful_queries": sum(1 for r in query_results if r["status"] == "success"),
                "failed_queries": sum(1 for r in query_results if r["status"] == "error"),
                "total_results_found": total_results,
                "total_successful_fetches": total_successful,
                "time_range_filter": time_range,
                "breadth_per_query": breadth,
            },
            "queries": query_list,
            "query_results": query_results,
            "all_suggestions": all_suggestions if include_suggestions else []
        }
        # ponytail: removed _generate_compiled_report — the LLM consumer can format its own report from structured JSON

        cache.set(cache_key, final_response, expire=1800)
        return JSONResponse(content=final_response)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Deep research failed: {str(e)}")


@app.get("/crawl-site")
async def crawl_site(
    start_url: str = Query(..., description="Starting URL to crawl"),
    max_pages: int = Query(50, description="Max pages (1-200)", ge=1, le=200),
    max_depth: int = Query(2, description="Max depth (0-5)", ge=0, le=5),
    format: str = Query("markdown", description="Output format: text, markdown, or html"),
    include_links: bool = Query(True, description="Include links"),
    include_images: bool = Query(True, description="Include images"),
    url_patterns: Optional[str] = Query(None, description="Comma-separated URL patterns to include"),
    exclude_patterns: Optional[str] = Query(None, description="Comma-separated URL patterns to exclude"),
    stealth_mode: str = Query("off", description="Stealth mode"),
    obey_robots: bool = Query(True, description="Obey robots.txt"),
):
    """Crawl a website and extract content from multiple pages."""
    parsed = urlparse(start_url)
    if not parsed.scheme or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Invalid URL format")

    start_url = validate_public_url(start_url)
    _validate_stealth_mode(stealth_mode)

    url_pattern_list = [p.strip() for p in url_patterns.split(",") if p.strip()] if url_patterns else None
    exclude_pattern_list = [p.strip() for p in exclude_patterns.split(",") if p.strip()] if exclude_patterns else None

    cache_key = f"crawl:{CACHE_VERSION}:{start_url}:{max_pages}:{max_depth}:{format}:{url_patterns}:{exclude_patterns}:{stealth_mode}:{obey_robots}"
    cached_result = cache.get(cache_key)
    if cached_result:
        return JSONResponse(content=cached_result)

    try:
        import subprocess
        import uuid

        results_filename = f"/tmp/scrapy_results_{uuid.uuid4().hex}.json"

        def sanitize_arg(arg: str) -> str:
            if '=' in arg:
                key, value = arg.split('=', 1)
                if not re.match(r'^[a-zA-Z0-9._\-:/@=]+$', value):
                    raise HTTPException(status_code=400, detail=f"Invalid characters in argument value: {value[:50]}")
                return f'{key}={value}'
            if not re.match(r'^[a-zA-Z0-9._\-:/,@\s]+$', arg):
                raise HTTPException(status_code=400, detail=f"Invalid characters in argument: {arg[:50]}")
            return arg

        cmd = [
            'scrapy', 'runspider',
            os.path.join(os.path.dirname(__file__), 'scrapy_crawler.py'),
            '-a', f'start_url={start_url}',
            '-a', f'max_pages={max_pages}',
            '-a', f'max_depth={max_depth}',
            '-a', f'format={format}',
            '-a', f'include_links={include_links}',
            '-a', f'include_images={include_images}',
            '-a', f'stealth_mode={stealth_mode}',
            '-o', results_filename,
            '-s', 'LOG_LEVEL=INFO',
            '-s', f'ROBOTSTXT_OBEY={str(obey_robots)}',
            '-s', 'CONCURRENT_REQUESTS=8',
            '-s', 'DOWNLOAD_DELAY=1',
            '-s', 'AUTOTHROTTLE_ENABLED=True',
        ]

        if stealth_mode != "off":
            cmd.extend(['-s', f'STEALTH_MODE={stealth_mode}'])

        if url_pattern_list:
            sanitized = ','.join(sanitize_arg(p) for p in url_pattern_list)
            cmd.extend(['-a', f'url_patterns={sanitized}'])
        if exclude_pattern_list:
            sanitized = ','.join(sanitize_arg(p) for p in exclude_pattern_list)
            cmd.extend(['-a', f'exclude_patterns={sanitized}'])

        # Sanitize user-provided values
        for i, arg in enumerate(cmd):
            if isinstance(arg, str) and i > 0 and cmd[i-1] in ('-a', '-s'):
                cmd[i] = sanitize_arg(arg)

        process = await asyncio.to_thread(
            subprocess.run, cmd,
            capture_output=True, text=True, timeout=900, cwd=os.path.dirname(__file__)
        )

        if process.returncode != 0:
            raise Exception(f"Scrapy failed with code {process.returncode}: {process.stderr}")

        if not os.path.exists(results_filename):
            raise Exception(f"Scrapy did not create results file")

        with open(results_filename, 'r') as f:
            content = f.read()
            if not content or content.strip() == '':
                raise Exception("Scrapy results file is empty")
            results = json.loads(content)

        os.unlink(results_filename)

        response_data = {
            "crawl_summary": {
                "start_url": start_url,
                "pages_crawled": len(results),
                "max_pages_requested": max_pages,
                "max_depth": max_depth,
                "format": format,
                "stealth_mode": stealth_mode,
            },
            "pages": results,
            "total_words": sum(r.get("word_count", 0) for r in results),
        }

        cache.set(cache_key, response_data, expire=1800)
        return JSONResponse(content=response_data)

    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Scrapy dependencies not installed: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Crawl failed: {str(e)}")


@app.get("/health")
@app.head("/health")
async def health_check():
    try:
        response = await get_http_client().get(SEARXNG_URL, timeout=5.0)
        searxng_status = "up" if response.status_code == 200 else "down"
    except Exception:
        searxng_status = "down"

    return {"status": "ok", "searxng": searxng_status, "searxng_url": SEARXNG_URL}


# ===== YouTube Transcript =====

YOUTUBE_ID_REGEXES = [
    r"(?:v=|/videos/|embed/|shorts/)([\w-]{11})",
    r"youtu\.be/([\w-]{11})",
    r"youtube\.com/watch\?.*v=([\w-]{11})",
    r"^([\w-]{11})$",
]


def extract_video_id(url_or_id: str) -> Optional[str]:
    s = url_or_id.strip()
    for pattern in YOUTUBE_ID_REGEXES:
        m = re.search(pattern, s)
        if m:
            return m.group(1)
    if re.fullmatch(r"[\w-]{11}", s):
        return s
    return None


def fetch_transcript_ytdlp(video_id: str, lang: Optional[str] = None) -> dict:
    """Fallback transcript fetcher using yt-dlp."""
    import subprocess
    import tempfile
    import shutil

    if not shutil.which("yt-dlp"):
        raise Exception("yt-dlp is not installed or not in PATH")

    url = f"https://www.youtube.com/watch?v={video_id}"

    try:
        result = subprocess.run(
            ["yt-dlp", "--extractor-args", "youtube:player_client=ios,web",
             "--no-check-certificates", "--list-subs", "--skip-download", "-J", url],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            raise Exception(f"yt-dlp failed: {(result.stderr or result.stdout)[:500]}")

        info = json.loads(result.stdout)
        subtitles = info.get("subtitles", {})
        auto_captions = info.get("automatic_captions", {})

        available_langs = [{"code": c, "is_generated": False} for c in subtitles]
        available_langs += [{"code": c, "is_generated": True} for c in auto_captions if c not in subtitles]

        if not available_langs:
            raise Exception("No subtitles available for this video")

    except FileNotFoundError:
        raise Exception("yt-dlp executable not found")
    except subprocess.TimeoutExpired:
        raise Exception("Timeout fetching subtitle info")
    except json.JSONDecodeError as e:
        raise Exception(f"Failed to parse yt-dlp output: {e}")

    # Determine language
    target_lang = lang
    if target_lang:
        if target_lang not in subtitles and target_lang not in auto_captions:
            for code in list(subtitles.keys()) + list(auto_captions.keys()):
                if code.startswith(target_lang) or target_lang.startswith(code.split('-')[0]):
                    target_lang = code
                    break
    else:
        target_lang = next(iter(subtitles), None) or next(iter(auto_captions), None)

    if not target_lang:
        raise Exception("No suitable subtitle track found")

    is_auto = target_lang in auto_captions and target_lang not in subtitles

    with tempfile.TemporaryDirectory() as tmpdir:
        sub_file = os.path.join(tmpdir, "sub")
        write_flag = "--write-sub" if target_lang in subtitles else "--write-auto-sub"

        cmd = [
            "yt-dlp", "--extractor-args", "youtube:player_client=ios,web",
            "--no-check-certificates", "--skip-download",
            write_flag, "--sub-lang", target_lang,
            "--sub-format", "json3", "--convert-subs", "json3",
            "-o", sub_file, url
        ]

        try:
            subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            raise Exception("Timeout downloading subtitles")

        sub_files = [f for f in os.listdir(tmpdir) if f.endswith('.json3')]
        if not sub_files:
            # Try vtt fallback
            cmd_vtt = [c if c != "json3" else "vtt" for c in cmd]
            subprocess.run(cmd_vtt, capture_output=True, text=True, timeout=120)
            sub_files = [f for f in os.listdir(tmpdir) if '.vtt' in f or '.json' in f]

        if not sub_files:
            raise Exception("Failed to download subtitles")

        sub_path = os.path.join(tmpdir, sub_files[0])
        with open(sub_path, 'r', encoding='utf-8') as f:
            content = f.read()

        transcript = []
        if sub_path.endswith('.json3'):
            data = json.loads(content)
            for event in data.get('events', []):
                if 'segs' in event:
                    text = ''.join(seg.get('utf8', '') for seg in event['segs']).strip()
                    if text:
                        transcript.append({
                            'start': event.get('tStartMs', 0) / 1000.0,
                            'duration': event.get('dDurationMs', 0) / 1000.0,
                            'text': text
                        })
        else:
            # VTT
            pattern = r'(\d{2}:\d{2}:\d{2}\.\d{3}) --> (\d{2}:\d{2}:\d{2}\.\d{3})\n(.+?)(?=\n\n|$)'
            for start_time, end_time, text in re.findall(pattern, content, re.DOTALL):
                def time_to_seconds(t):
                    parts = t.replace(',', '.').split(':')
                    return float(parts[0])*3600 + float(parts[1])*60 + float(parts[2])
                start = time_to_seconds(start_time)
                end = time_to_seconds(end_time)
                clean_text = re.sub(r'<[^>]+>', '', text).strip()
                if clean_text:
                    transcript.append({'start': start, 'duration': end - start, 'text': clean_text})

        return {
            'transcript': transcript,
            'language': target_lang,
            'is_generated': is_auto,
            'available_langs': available_langs
        }


@app.get("/yt-transcript")
async def youtube_transcript(
    video: str = Query(..., description="YouTube video URL or 11-character video ID"),
    format: str = Query("text", description="Output format: text, json, or srt"),
    lang: Optional[str] = Query(None, description="Preferred language code"),
    translate: Optional[str] = Query(None, description="Translate to target language"),
    start: Optional[float] = Query(None, description="Start time in seconds"),
    end: Optional[float] = Query(None, description="End time in seconds"),
    list_langs: bool = Query(False, description="List available languages instead"),
):
    """Fetch YouTube video transcripts."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api.formatters import TextFormatter, JSONFormatter, SRTFormatter
    except ImportError:
        raise HTTPException(status_code=503, detail="youtube-transcript-api not installed")

    valid_formats = {"text", "json", "srt"}
    if format.lower() not in valid_formats:
        raise HTTPException(status_code=400, detail=f"Format must be one of: {', '.join(valid_formats)}")

    video_id = extract_video_id(video)
    if not video_id:
        raise HTTPException(status_code=400, detail="Could not extract YouTube video ID")

    cache_key = f"yt:{CACHE_VERSION}:{video_id}:{format}:{lang}:{translate}:{start}:{end}:{list_langs}"
    cached_result = cache.get(cache_key)
    if cached_result:
        return JSONResponse(content=cached_result)

    try:
        ytt_api = YouTubeTranscriptApi()

        if list_langs:
            transcript_list = ytt_api.list(video_id)
            langs = [{"language_code": t.language_code, "language": t.language,
                       "is_generated": t.is_generated, "is_translatable": t.is_translatable}
                     for t in transcript_list]
            result = {"video_id": video_id, "available_transcripts": langs}
            cache.set(cache_key, result, expire=3600)
            return JSONResponse(content=result)

        transcript = None
        actual_language = None

        if translate:
            transcript_list = ytt_api.list(video_id)
            available = list(transcript_list)
            if lang:
                try:
                    source = transcript_list.find_transcript([lang])
                except Exception:
                    source = available[0] if available else None
            else:
                source = available[0] if available else None
            if not source:
                raise HTTPException(status_code=404, detail="No transcripts available")
            actual_language = source.language_code
            transcript = source.translate(translate).fetch()
        elif lang:
            transcript = ytt_api.fetch(video_id, languages=[lang])
            actual_language = lang
        else:
            try:
                transcript_list = ytt_api.list(video_id)
                available = list(transcript_list)
                if not available:
                    raise HTTPException(status_code=404, detail="No transcripts available")
                manual = [t for t in available if not t.is_generated]
                source = manual[0] if manual else available[0]
                actual_language = source.language_code
                transcript = source.fetch()
            except HTTPException:
                raise
            except Exception:
                transcript = ytt_api.fetch(video_id)
                actual_language = "auto"

        # Time slicing
        if start is not None or end is not None:
            raw_data = transcript.to_raw_data()
            transcript = [e for e in raw_data if (start is None or e.get("start", 0) >= start) and (end is None or e.get("start", 0) <= end)]

        # Format
        fmt = format.lower()
        formatters = {"text": TextFormatter(), "json": JSONFormatter(), "srt": SRTFormatter()}
        if fmt == "json":
            formatted_output = formatters[fmt].format_transcript(transcript, indent=2)
        else:
            formatted_output = formatters[fmt].format_transcript(transcript)

        raw_data = transcript.to_raw_data() if hasattr(transcript, 'to_raw_data') else transcript
        total_duration = max((e.get("start", 0) + e.get("duration", 0) for e in raw_data), default=0)
        word_count = sum(len(e.get("text", "").split()) for e in raw_data)

        result = {
            "success": True,
            "video_id": video_id,
            "video_url": f"https://www.youtube.com/watch?v={video_id}",
            "format": fmt,
            "language": actual_language or "auto",
            "translated_to": translate,
            "time_range": {"start": start, "end": end} if start or end else None,
            "stats": {"segment_count": len(raw_data), "word_count": word_count, "duration_seconds": round(total_duration, 2)},
            "transcript": formatted_output
        }

        cache.set(cache_key, result, expire=3600)
        return JSONResponse(content=result)

    except HTTPException:
        raise
    except Exception as e:
        # Fallback to yt-dlp
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"youtube-transcript-api failed for {video_id}: {e}")
        try:
            ytdlp_result = await asyncio.get_event_loop().run_in_executor(
                None, lambda: fetch_transcript_ytdlp(video_id, lang)
            )

            if list_langs:
                result = {
                    "video_id": video_id, "source": "yt-dlp",
                    "available_transcripts": [
                        {"language_code": l["code"], "language": l["code"],
                         "is_generated": l["is_generated"], "is_translatable": False}
                        for l in ytdlp_result["available_langs"]
                    ]
                }
                cache.set(cache_key, result, expire=3600)
                return JSONResponse(content=result)

            transcript = ytdlp_result["transcript"]
            actual_language = ytdlp_result["language"]

            if start is not None or end is not None:
                transcript = [e for e in transcript if (start is None or e.get("start", 0) >= start) and (end is None or e.get("start", 0) <= end)]

            fmt = format.lower()
            if fmt == "text":
                formatted_output = "\n".join(e["text"] for e in transcript)
            elif fmt == "json":
                formatted_output = json.dumps(transcript, indent=2)
            elif fmt == "srt":
                srt_lines = []
                for i, entry in enumerate(transcript, 1):
                    s = entry["start"]
                    e_time = s + entry.get("duration", 0)
                    def fmt_srt(sec):
                        h, m, sec2 = int(sec//3600), int((sec%3600)//60), sec%60
                        return f"{h:02d}:{m:02d}:{int(sec2):02d},{int((sec2%1)*1000):03d}"
                    srt_lines.extend([str(i), f"{fmt_srt(s)} --> {fmt_srt(e_time)}", entry["text"], ""])
                formatted_output = "\n".join(srt_lines)
            else:
                formatted_output = str(transcript)

            total_duration = max((e.get("start", 0) + e.get("duration", 0) for e in transcript), default=0)
            word_count = sum(len(e.get("text", "").split()) for e in transcript)

            result = {
                "success": True, "video_id": video_id,
                "video_url": f"https://www.youtube.com/watch?v={video_id}",
                "format": fmt, "language": actual_language, "translated_to": None,
                "time_range": {"start": start, "end": end} if start or end else None,
                "stats": {"segment_count": len(transcript), "word_count": word_count, "duration_seconds": round(total_duration, 2)},
                "transcript": formatted_output, "source": "yt-dlp"
            }
            cache.set(cache_key, result, expire=3600)
            return JSONResponse(content=result)

        except Exception as ytdlp_error:
            err = str(e).lower()
            if "no transcript" in err or "could not retrieve" in err:
                raise HTTPException(status_code=404, detail=f"No transcript found. Primary: {str(e)[:200]}. Fallback: {str(ytdlp_error)[:200]}")
            if "disabled" in err:
                raise HTTPException(status_code=403, detail="Transcripts are disabled for this video.")
            if "unavailable" in err:
                raise HTTPException(status_code=404, detail="Video unavailable.")
            raise HTTPException(status_code=500, detail=f"Failed: {str(e)[:300]}. Fallback: {str(ytdlp_error)[:300]}")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8001))
    uvicorn.run(app, host="0.0.0.0", port=port)
