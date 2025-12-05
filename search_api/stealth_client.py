"""
Stealth HTTP Client for Anti-Bot Bypass

Provides HTTP client with anti-detection capabilities:
- User-Agent rotation across multiple browsers
- Header randomization to avoid fingerprinting
- TLS fingerprint matching (via curl_cffi)
- Realistic header combinations per browser type
"""

import random
import asyncio
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass
from enum import Enum

try:
    from curl_cffi.requests import AsyncSession
    CURL_CFFI_AVAILABLE = True
except ImportError:
    CURL_CFFI_AVAILABLE = False

import httpx


class StealthLevel(Enum):
    """Stealth levels for anti-bot bypass"""
    LOW = "low"        # Basic UA rotation
    MEDIUM = "medium"  # UA + header randomization
    HIGH = "high"      # UA + headers + TLS fingerprint (curl_cffi)


class BrowserType(Enum):
    """Browser types for realistic fingerprinting"""
    CHROME_WIN = "chrome_win"
    CHROME_MAC = "chrome_mac"
    CHROME_LINUX = "chrome_linux"
    FIREFOX_WIN = "firefox_win"
    FIREFOX_MAC = "firefox_mac"
    SAFARI_MAC = "safari_mac"
    EDGE_WIN = "edge_win"
    CHROME_ANDROID = "chrome_android"
    SAFARI_IOS = "safari_ios"


@dataclass
class StealthResponse:
    """Response from stealth client"""
    status_code: int
    text: str
    headers: Dict[str, str]
    url: str
    browser_used: str
    stealth_level: str


# User-Agent strings for different browsers (updated for 2024-2025)
USER_AGENTS = {
    BrowserType.CHROME_WIN: [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    ],
    BrowserType.CHROME_MAC: [
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    ],
    BrowserType.CHROME_LINUX: [
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    ],
    BrowserType.FIREFOX_WIN: [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    ],
    BrowserType.FIREFOX_MAC: [
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:122.0) Gecko/20100101 Firefox/122.0",
    ],
    BrowserType.SAFARI_MAC: [
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    ],
    BrowserType.EDGE_WIN: [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0",
    ],
    BrowserType.CHROME_ANDROID: [
        "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
        "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
    ],
    BrowserType.SAFARI_IOS: [
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Mobile/15E148 Safari/604.1",
    ],
}

# TLS fingerprint identifiers for curl_cffi (impersonate parameter)
TLS_FINGERPRINTS = {
    BrowserType.CHROME_WIN: "chrome120",
    BrowserType.CHROME_MAC: "chrome120",
    BrowserType.CHROME_LINUX: "chrome120",
    BrowserType.FIREFOX_WIN: "firefox121",
    BrowserType.FIREFOX_MAC: "firefox121",
    BrowserType.SAFARI_MAC: "safari17_2_ios",
    BrowserType.EDGE_WIN: "edge101",
    BrowserType.CHROME_ANDROID: "chrome120",
    BrowserType.SAFARI_IOS: "safari17_2_ios",
}


def get_headers_for_browser(browser_type: BrowserType, user_agent: str) -> Dict[str, str]:
    """Generate realistic headers for a specific browser type"""
    
    base_headers = {
        "User-Agent": user_agent,
        "Accept-Language": random.choice([
            "en-US,en;q=0.9",
            "en-US,en;q=0.9,es;q=0.8",
            "en-GB,en;q=0.9,en-US;q=0.8",
        ]),
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    
    # Browser-specific headers
    if browser_type in [BrowserType.CHROME_WIN, BrowserType.CHROME_MAC, BrowserType.CHROME_LINUX, BrowserType.CHROME_ANDROID]:
        base_headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            "sec-ch-ua-mobile": "?0" if "Android" not in user_agent else "?1",
            "sec-ch-ua-platform": '"Windows"' if "Windows" in user_agent else '"macOS"' if "Mac" in user_agent else '"Linux"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
        })
    elif browser_type in [BrowserType.FIREFOX_WIN, BrowserType.FIREFOX_MAC]:
        base_headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
        })
    elif browser_type in [BrowserType.SAFARI_MAC, BrowserType.SAFARI_IOS]:
        base_headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
    elif browser_type == BrowserType.EDGE_WIN:
        base_headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Microsoft Edge";v="120"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
        })
    
    return base_headers


def randomize_header_order(headers: Dict[str, str]) -> Dict[str, str]:
    """Randomize header order to avoid fingerprinting"""
    items = list(headers.items())
    random.shuffle(items)
    return dict(items)


class StealthClient:
    """
    HTTP client with anti-bot detection capabilities
    
    Stealth Levels:
    - LOW: Basic User-Agent rotation
    - MEDIUM: UA rotation + header randomization
    - HIGH: UA + headers + TLS fingerprint matching (requires curl_cffi)
    """
    
    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout
        self._session: Optional[AsyncSession] = None
    
    def _select_browser(self) -> Tuple[BrowserType, str]:
        """Select a random browser type and user agent"""
        # Weight desktop browsers more heavily
        weights = {
            BrowserType.CHROME_WIN: 35,
            BrowserType.CHROME_MAC: 20,
            BrowserType.FIREFOX_WIN: 10,
            BrowserType.FIREFOX_MAC: 5,
            BrowserType.SAFARI_MAC: 10,
            BrowserType.EDGE_WIN: 10,
            BrowserType.CHROME_ANDROID: 5,
            BrowserType.SAFARI_IOS: 5,
        }
        
        browser_type = random.choices(
            list(weights.keys()),
            weights=list(weights.values()),
            k=1
        )[0]
        
        user_agent = random.choice(USER_AGENTS[browser_type])
        return browser_type, user_agent
    
    async def get(
        self,
        url: str,
        stealth_level: StealthLevel = StealthLevel.MEDIUM,
        follow_redirects: bool = True,
        extra_headers: Optional[Dict[str, str]] = None
    ) -> StealthResponse:
        """
        Make a GET request with stealth capabilities
        
        Args:
            url: URL to fetch
            stealth_level: Level of stealth measures to apply
            follow_redirects: Whether to follow redirects
            extra_headers: Additional headers to include
            
        Returns:
            StealthResponse with status, text, headers, and metadata
        """
        browser_type, user_agent = self._select_browser()
        
        if stealth_level == StealthLevel.LOW:
            # Just rotate User-Agent
            headers = {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
            }
            return await self._fetch_with_httpx(url, headers, follow_redirects, browser_type, stealth_level)
        
        elif stealth_level == StealthLevel.MEDIUM:
            # UA rotation + header randomization
            headers = get_headers_for_browser(browser_type, user_agent)
            if extra_headers:
                headers.update(extra_headers)
            headers = randomize_header_order(headers)
            return await self._fetch_with_httpx(url, headers, follow_redirects, browser_type, stealth_level)
        
        elif stealth_level == StealthLevel.HIGH:
            # Full stealth with TLS fingerprinting
            if CURL_CFFI_AVAILABLE:
                return await self._fetch_with_curl_cffi(url, browser_type, user_agent, follow_redirects, extra_headers)
            else:
                # Fallback to medium if curl_cffi not available
                headers = get_headers_for_browser(browser_type, user_agent)
                if extra_headers:
                    headers.update(extra_headers)
                headers = randomize_header_order(headers)
                return await self._fetch_with_httpx(url, headers, follow_redirects, browser_type, StealthLevel.MEDIUM)
    
    async def _fetch_with_httpx(
        self,
        url: str,
        headers: Dict[str, str],
        follow_redirects: bool,
        browser_type: BrowserType,
        stealth_level: StealthLevel
    ) -> StealthResponse:
        """Fetch using httpx with custom headers"""
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=follow_redirects,
            http2=True
        ) as client:
            response = await client.get(url, headers=headers)
            return StealthResponse(
                status_code=response.status_code,
                text=response.text,
                headers=dict(response.headers),
                url=str(response.url),
                browser_used=browser_type.value,
                stealth_level=stealth_level.value
            )
    
    async def _fetch_with_curl_cffi(
        self,
        url: str,
        browser_type: BrowserType,
        user_agent: str,
        follow_redirects: bool,
        extra_headers: Optional[Dict[str, str]] = None
    ) -> StealthResponse:
        """Fetch using curl_cffi with TLS fingerprint impersonation"""
        fingerprint = TLS_FINGERPRINTS.get(browser_type, "chrome120")
        
        headers = get_headers_for_browser(browser_type, user_agent)
        if extra_headers:
            headers.update(extra_headers)
        
        async with AsyncSession() as session:
            response = await session.get(
                url,
                headers=headers,
                impersonate=fingerprint,
                allow_redirects=follow_redirects,
                timeout=self.timeout
            )
            return StealthResponse(
                status_code=response.status_code,
                text=response.text,
                headers=dict(response.headers),
                url=str(response.url),
                browser_used=browser_type.value,
                stealth_level=StealthLevel.HIGH.value
            )
    
    async def close(self):
        """Clean up resources"""
        if self._session:
            await self._session.close()
            self._session = None


# Convenience function for one-off requests
async def stealth_get(
    url: str,
    stealth_level: str = "medium",
    timeout: float = 30.0
) -> StealthResponse:
    """
    Make a stealth GET request
    
    Args:
        url: URL to fetch
        stealth_level: "low", "medium", or "high"
        timeout: Request timeout in seconds
        
    Returns:
        StealthResponse object
    """
    level = StealthLevel(stealth_level.lower())
    client = StealthClient(timeout=timeout)
    try:
        return await client.get(url, stealth_level=level)
    finally:
        await client.close()
