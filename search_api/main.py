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
from dateutil import parser as date_parser
from datetime import datetime, timedelta
import re
from diskcache import Cache
from flashrank import Ranker, RerankRequest
import os
import json
import unicodedata
import gzip
import zlib
from io import BytesIO

# Try to import brotli for brotli decompression
try:
    import brotli
    BROTLI_AVAILABLE = True
except ImportError:
    BROTLI_AVAILABLE = False

# Import free stealth and bot detection modules (no API keys needed)
from stealth_client import StealthClient, StealthLevel, stealth_get


def decompress_content(raw_bytes: bytes, content_encoding: str = None) -> bytes:
    """
    Attempt to decompress the content using various compression algorithms.
    Returns decompressed bytes or original bytes if decompression fails/not needed.
    """
    if not raw_bytes:
        return raw_bytes
    
    # Try to detect compression from magic bytes
    is_gzip = raw_bytes[:2] == b'\x1f\x8b'
    is_zlib = raw_bytes[:2] in [b'\x78\x9c', b'\x78\x01', b'\x78\xda']
    is_brotli = content_encoding and 'br' in content_encoding.lower()
    
    # Try gzip first
    if is_gzip or (content_encoding and 'gzip' in content_encoding.lower()):
        try:
            return gzip.decompress(raw_bytes)
        except Exception:
            pass
    
    # Try deflate/zlib
    if is_zlib or (content_encoding and 'deflate' in content_encoding.lower()):
        try:
            return zlib.decompress(raw_bytes)
        except Exception:
            try:
                # Try raw deflate (no zlib header)
                return zlib.decompress(raw_bytes, -zlib.MAX_WBITS)
            except Exception:
                pass
    
    # Try brotli if available
    if BROTLI_AVAILABLE and (is_brotli or content_encoding):
        try:
            return brotli.decompress(raw_bytes)
        except Exception:
            pass
    
    # If nothing worked, try all decompression methods as fallback
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
    """
    Try multiple encodings to decode bytes to string.
    Returns decoded string with best encoding found.
    """
    if not raw_bytes:
        return ""
    
    # Try to extract charset from content-type header
    charset = None
    if content_type:
        for part in content_type.split(';'):
            if 'charset=' in part.lower():
                charset = part.split('=')[1].strip().strip('"\'')
                break
    
    # Build list of encodings to try
    encodings_to_try = []
    if charset:
        encodings_to_try.append(charset)
    encodings_to_try.extend(['utf-8', 'utf-8-sig', 'latin-1', 'cp1252', 'iso-8859-1', 'ascii'])
    
    # Remove duplicates while preserving order
    seen = set()
    encodings_to_try = [x for x in encodings_to_try if not (x.lower() in seen or seen.add(x.lower()))]
    
    # Try each encoding
    for encoding in encodings_to_try:
        try:
            decoded = raw_bytes.decode(encoding)
            # Check if it looks like valid HTML/text
            if '<html' in decoded.lower() or '<body' in decoded.lower() or '<div' in decoded.lower():
                return decoded
            # Still valid, might be non-HTML
            if decoded and len(decoded) > 10:
                return decoded
        except (UnicodeDecodeError, LookupError):
            continue
    
    # Last resort: decode with errors='replace'
    return raw_bytes.decode('utf-8', errors='replace')


def sanitize_content(content: str) -> str:
    """
    Remove NULL bytes and invalid control characters from content.
    Ensures the content is valid for XML/JSON serialization.
    """
    if not content:
        return content
    
    # Remove NULL bytes
    content = content.replace('\x00', '')
    
    # Remove other problematic control characters (keep newlines, tabs, carriage returns)
    # XML 1.0 valid chars: #x9 | #xA | #xD | [#x20-#xD7FF] | [#xE000-#xFFFD]
    def is_valid_xml_char(c):
        codepoint = ord(c)
        return (
            codepoint == 0x9 or  # Tab
            codepoint == 0xA or  # Newline
            codepoint == 0xD or  # Carriage return
            (0x20 <= codepoint <= 0xD7FF) or
            (0xE000 <= codepoint <= 0xFFFD) or
            (0x10000 <= codepoint <= 0x10FFFF)
        )
    
    # Filter out invalid characters
    sanitized = ''.join(c for c in content if is_valid_xml_char(c))
    
    return sanitized


def is_valid_html(content: str) -> bool:
    """Check if content appears to be valid HTML."""
    if not content or len(content.strip()) < 10:
        return False
    
    lower_content = content[:5000].lower()
    html_indicators = ['<html', '<head', '<body', '<div', '<p>', '<a ', '<!doctype', '<meta']
    return any(indicator in lower_content for indicator in html_indicators)


async def robust_fetch_content(
    url: str,
    headers: dict = None,
    timeout: float = 30.0,
    follow_redirects: bool = True
) -> dict:
    """
    Robust content fetching that handles compression and encoding issues.
    Returns dict with 'html', 'status_code', 'final_url', 'content_type', 'encoding_used'.
    """
    import httpx
    
    default_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1"
    }
    
    if headers:
        default_headers.update(headers)
    
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=follow_redirects,
    ) as client:
        response = await client.get(url, headers=default_headers)
        response.raise_for_status()
        
        # Get raw bytes
        raw_bytes = response.content
        
        # Get headers for content type and encoding
        content_type = response.headers.get('content-type', '')
        content_encoding = response.headers.get('content-encoding', '')
        
        # Step 1: Try to decompress if needed
        decompressed_bytes = decompress_content(raw_bytes, content_encoding)
        
        # Step 2: Decode to string with multiple encoding attempts
        html_content = decode_content(decompressed_bytes, content_type)
        
        # Step 3: Sanitize the content
        html_content = sanitize_content(html_content)
        
        # Step 4: Validate we got something useful
        if not is_valid_html(html_content) and len(html_content) < 100:
            # Try one more time with the raw response.text (httpx might handle it better)
            try:
                html_content = sanitize_content(response.text)
            except Exception:
                pass
        
        return {
            "html": html_content,
            "status_code": response.status_code,
            "final_url": str(response.url),
            "content_type": content_type,
            "encoding_used": content_encoding or "none"
        }


from antibot import detect_protection, is_blocked, ProtectionType

# Initialize DiskCache
cache = Cache("/tmp/miyami_cache")

# Global Ranker (Lazy loaded)
_ranker = None

# Global Stealth Client (Lazy loaded)
_stealth_client = None

def get_ranker():
    global _ranker
    if _ranker is None:
        # Use a lightweight model
        _ranker = Ranker(model_name="ms-marco-TinyBERT-L-2-v2", cache_dir="/tmp/flashrank")
    return _ranker

def get_stealth_client():
    global _stealth_client
    if _stealth_client is None:
        _stealth_client = StealthClient(timeout=30.0)
    return _stealth_client


async def advanced_fetch(
    url: str,
    stealth_mode: str = "off",
    auto_bypass: bool = False
) -> Dict[str, Any]:
    """
    Advanced fetch with stealth mode for anti-bot bypass (FREE - no API keys needed).
    Includes robust handling of compressed and encoded content.
    
    Args:
        url: URL to fetch
        stealth_mode: "off", "low", "medium", or "high"
        auto_bypass: Automatically try higher stealth levels if blocked
        
    Returns:
        Dict with html, status_code, final_url, fetch_method, protection_info
    """
    fetch_method = "standard"
    protection_info = None
    html = ""
    status_code = 0
    final_url = url
    
    # Helper function to process raw response bytes
    def process_response_content(response_content: bytes, response_headers: dict) -> str:
        """Process raw bytes with decompression and decoding."""
        content_encoding = response_headers.get('content-encoding', '')
        content_type = response_headers.get('content-type', '')
        
        # Step 1: Decompress if needed
        decompressed = decompress_content(response_content, content_encoding)
        
        # Step 2: Decode with multiple encoding attempts
        decoded = decode_content(decompressed, content_type)
        
        # Step 3: Sanitize to remove invalid characters
        sanitized = sanitize_content(decoded)
        
        return sanitized
    
    # Step 1: Fetch using stealth mode or standard
    if stealth_mode != "off":
        # Use stealth client (FREE - no API keys needed)
        try:
            level = StealthLevel(stealth_mode.lower())
            client = get_stealth_client()
            response = await client.get(url, stealth_level=level)
            
            # Use raw bytes for proper decompression handling
            if response.content and len(response.content) > 0:
                html = process_response_content(
                    response.content,
                    {"content-encoding": response.content_encoding, "content-type": response.headers.get("content-type", "")}
                )
            else:
                html = sanitize_content(response.text)
            
            # Fallback: If content still looks corrupted, try re-processing
            if not is_valid_html(html) and len(html) > 100:
                try:
                    raw_bytes = response.text.encode('latin-1', errors='ignore')
                    decompressed = decompress_content(raw_bytes, None)
                    html = decode_content(decompressed, None)
                    html = sanitize_content(html)
                except Exception:
                    pass
            
            status_code = response.status_code
            final_url = response.url
            fetch_method = f"stealth_{stealth_mode}"
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Stealth fetch failed: {str(e)}")
    else:
        # Standard fetch with raw bytes handling
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
        ) as client:
            response = await client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "DNT": "1",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1"
            })
            response.raise_for_status()
            
            # Process raw bytes with proper decompression and decoding
            html = process_response_content(
                response.content,
                dict(response.headers)
            )
            
            # Fallback to response.text if our processing failed
            if not is_valid_html(html) or len(html) < 50:
                try:
                    html = sanitize_content(response.text)
                except Exception:
                    pass
            
            status_code = response.status_code
            final_url = str(response.url)
    
    # Step 2: Check for bot protection (FREE detection)
    protection = detect_protection(html)
    if protection.is_protected:
        protection_info = {
            "detected": True,
            "is_blocked": protection.is_blocked,
            "protections": [p.value for p in protection.protections],
            "confidence": protection.confidence,
            "recommendation": protection.recommendation
        }
        
        # Auto-bypass: try escalating to higher stealth levels (FREE)
        if protection.is_blocked and auto_bypass:
            if fetch_method == "standard" or fetch_method == "stealth_low":
                # Try medium stealth
                try:
                    client = get_stealth_client()
                    response = await client.get(url, stealth_level=StealthLevel.MEDIUM)
                    new_html = sanitize_content(response.text)
                    new_protection = detect_protection(new_html)
                    
                    if not new_protection.is_blocked:
                        html = new_html
                        status_code = response.status_code
                        final_url = response.url
                        fetch_method = "stealth_medium_auto"
                        protection_info["bypassed"] = True
                        protection_info["bypass_method"] = "stealth_medium"
                except:
                    pass
            
            # Still blocked? Try high stealth
            if protection.is_blocked and fetch_method not in ["stealth_high", "stealth_medium_auto"]:
                try:
                    client = get_stealth_client()
                    response = await client.get(url, stealth_level=StealthLevel.HIGH)
                    new_html = sanitize_content(response.text)
                    new_protection = detect_protection(new_html)
                    
                    if not new_protection.is_blocked:
                        html = new_html
                        status_code = response.status_code
                        final_url = response.url
                        fetch_method = "stealth_high_auto"
                        protection_info["bypassed"] = True
                        protection_info["bypass_method"] = "stealth_high"
                except:
                    pass
    
    # Step 3: Final validation - try to extract SOMETHING even if content looks bad
    if not html or len(html.strip()) < 10:
        # Last resort: return whatever we have with a warning
        html = "[Content could not be fully extracted]"
    
    return {
        "html": html,
        "status_code": status_code,
        "final_url": final_url,
        "fetch_method": fetch_method,
        "protection_info": protection_info
    }


app = FastAPI(
    title="SearXNG Search API",
    description="FastAPI wrapper for SearXNG with search and fetch capabilities",
    version="1.0.0"
)

SEARXNG_URL = "http://127.0.0.1:8888"

# HTML GUI Template
GUI_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Miyami Search API</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
            min-height: 100vh;
            color: #e4e4e4;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }
        
        header {
            text-align: center;
            padding: 40px 20px;
            background: rgba(255,255,255,0.05);
            border-radius: 20px;
            margin-bottom: 30px;
            backdrop-filter: blur(10px);
        }
        
        header h1 {
            font-size: 2.5rem;
            background: linear-gradient(90deg, #00d4ff, #7b2cbf, #e040fb);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            margin-bottom: 10px;
        }
        
        header p {
            color: #a0a0a0;
            font-size: 1.1rem;
        }
        
        .tools-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 25px;
            margin-bottom: 30px;
        }
        
        .tool-card {
            background: rgba(255,255,255,0.08);
            border-radius: 16px;
            padding: 25px;
            border: 1px solid rgba(255,255,255,0.1);
            transition: all 0.3s ease;
        }
        
        .tool-card:hover {
            transform: translateY(-5px);
            border-color: rgba(0,212,255,0.4);
            box-shadow: 0 20px 40px rgba(0,0,0,0.3);
        }
        
        .tool-card h3 {
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 1.3rem;
            margin-bottom: 15px;
            color: #00d4ff;
        }
        
        .tool-card h3 .icon {
            font-size: 1.5rem;
        }
        
        .tool-card .description {
            color: #a0a0a0;
            font-size: 0.9rem;
            margin-bottom: 20px;
            line-height: 1.5;
        }
        
        .form-group {
            margin-bottom: 15px;
        }
        
        .form-group label {
            display: block;
            font-size: 0.85rem;
            color: #b0b0b0;
            margin-bottom: 6px;
        }
        
        .form-group input, .form-group select, .form-group textarea {
            width: 100%;
            padding: 12px 15px;
            border: 1px solid rgba(255,255,255,0.15);
            border-radius: 10px;
            background: rgba(0,0,0,0.3);
            color: #fff;
            font-size: 0.95rem;
            transition: all 0.2s ease;
        }
        
        .form-group input:focus, .form-group select:focus, .form-group textarea:focus {
            outline: none;
            border-color: #00d4ff;
            box-shadow: 0 0 0 3px rgba(0,212,255,0.15);
        }
        
        .form-group input::placeholder {
            color: #666;
        }
        
        .form-row {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
        }
        
        .btn {
            width: 100%;
            padding: 14px 20px;
            border: none;
            border-radius: 10px;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
        }
        
        .btn-primary {
            background: linear-gradient(135deg, #00d4ff 0%, #7b2cbf 100%);
            color: white;
        }
        
        .btn-primary:hover {
            transform: scale(1.02);
            box-shadow: 0 10px 30px rgba(0,212,255,0.3);
        }
        
        .btn-primary:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }
        
        .checkbox-group {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .checkbox-group input[type="checkbox"] {
            width: 18px;
            height: 18px;
            accent-color: #00d4ff;
        }
        
        .checkbox-group label {
            margin-bottom: 0;
            cursor: pointer;
        }
        
        .result-section {
            background: rgba(255,255,255,0.05);
            border-radius: 16px;
            padding: 25px;
            margin-top: 30px;
            border: 1px solid rgba(255,255,255,0.1);
        }
        
        .result-section h2 {
            font-size: 1.4rem;
            margin-bottom: 20px;
            color: #00d4ff;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .result-box {
            background: rgba(0,0,0,0.4);
            border-radius: 12px;
            padding: 20px;
            max-height: 500px;
            overflow-y: auto;
            font-family: 'Monaco', 'Menlo', monospace;
            font-size: 0.85rem;
            line-height: 1.6;
            white-space: pre-wrap;
            word-break: break-word;
        }
        
        .result-box.loading {
            text-align: center;
            color: #00d4ff;
        }
        
        .result-box .error {
            color: #ff6b6b;
        }
        
        .result-box .success {
            color: #51cf66;
        }
        
        .loading-spinner {
            display: inline-block;
            width: 20px;
            height: 20px;
            border: 2px solid rgba(255,255,255,0.3);
            border-radius: 50%;
            border-top-color: #00d4ff;
            animation: spin 1s linear infinite;
        }
        
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        
        .quick-links {
            display: flex;
            justify-content: center;
            gap: 20px;
            margin-top: 30px;
            flex-wrap: wrap;
        }
        
        .quick-links a {
            color: #00d4ff;
            text-decoration: none;
            padding: 10px 20px;
            border: 1px solid rgba(0,212,255,0.3);
            border-radius: 8px;
            transition: all 0.2s ease;
            font-size: 0.9rem;
        }
        
        .quick-links a:hover {
            background: rgba(0,212,255,0.1);
            border-color: #00d4ff;
        }
        
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin-top: 20px;
        }
        
        .stat-item {
            background: rgba(0,0,0,0.3);
            padding: 15px;
            border-radius: 10px;
            text-align: center;
        }
        
        .stat-item .value {
            font-size: 1.5rem;
            font-weight: bold;
            color: #00d4ff;
        }
        
        .stat-item .label {
            font-size: 0.8rem;
            color: #888;
            margin-top: 5px;
        }
        
        @media (max-width: 768px) {
            .tools-grid {
                grid-template-columns: 1fr;
            }
            .form-row {
                grid-template-columns: 1fr;
            }
            header h1 {
                font-size: 1.8rem;
            }
        }
        
        /* Scrollbar styling */
        ::-webkit-scrollbar {
            width: 8px;
        }
        ::-webkit-scrollbar-track {
            background: rgba(255,255,255,0.05);
            border-radius: 4px;
        }
        ::-webkit-scrollbar-thumb {
            background: rgba(0,212,255,0.4);
            border-radius: 4px;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: rgba(0,212,255,0.6);
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🔍 Miyami Search API</h1>
            <p>LLM-Optimized Web Search & Content Extraction Tools</p>
        </header>
        
        <div class="tools-grid">
            <!-- Search Tool -->
            <div class="tool-card">
                <h3><span class="icon">🔎</span> Web Search</h3>
                <p class="description">Search the web using multiple engines (DuckDuckGo, Google, Bing, Brave, Wikipedia)</p>
                <form id="searchForm">
                    <div class="form-group">
                        <label>Search Query</label>
                        <input type="text" name="query" placeholder="e.g., latest AI news" required>
                    </div>
                    <div class="form-row">
                        <div class="form-group">
                            <label>Time Range</label>
                            <select name="time_range">
                                <option value="">All Time</option>
                                <option value="day">Past 24 Hours</option>
                                <option value="week">Past Week</option>
                                <option value="month">Past Month</option>
                                <option value="year">Past Year</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label>Category</label>
                            <select name="categories">
                                <option value="general">General</option>
                                <option value="news">News</option>
                                <option value="images">Images</option>
                                <option value="videos">Videos</option>
                                <option value="science">Science</option>
                            </select>
                        </div>
                    </div>
                    <div class="form-group checkbox-group">
                        <input type="checkbox" name="rerank" id="rerank">
                        <label for="rerank">AI Reranking (better relevance)</label>
                    </div>
                    <button type="submit" class="btn btn-primary">🔍 Search</button>
                </form>
            </div>
            
            <!-- Fetch Tool -->
            <div class="tool-card">
                <h3><span class="icon">📄</span> Fetch Content</h3>
                <p class="description">Extract clean, readable content from any webpage with optional stealth mode</p>
                <form id="fetchForm">
                    <div class="form-group">
                        <label>URL to Fetch</label>
                        <input type="url" name="url" placeholder="https://example.com/article" required>
                    </div>
                    <div class="form-row">
                        <div class="form-group">
                            <label>Output Format</label>
                            <select name="output_format">
                                <option value="markdown">Markdown</option>
                                <option value="text">Plain Text</option>
                                <option value="html">HTML</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label>Stealth Mode</label>
                            <select name="stealth_mode">
                                <option value="off">Off</option>
                                <option value="low">Low</option>
                                <option value="medium">Medium</option>
                                <option value="high">High</option>
                            </select>
                        </div>
                    </div>
                    <div class="form-group checkbox-group">
                        <input type="checkbox" name="auto_bypass" id="auto_bypass">
                        <label for="auto_bypass">Auto Bypass (escalate if blocked)</label>
                    </div>
                    <button type="submit" class="btn btn-primary">📄 Fetch Content</button>
                </form>
            </div>
            
            <!-- Search & Fetch Tool -->
            <div class="tool-card">
                <h3><span class="icon">🔗</span> Search & Fetch</h3>
                <p class="description">Search and automatically extract content from top results</p>
                <form id="searchFetchForm">
                    <div class="form-group">
                        <label>Search Query</label>
                        <input type="text" name="query" placeholder="e.g., Python best practices" required>
                    </div>
                    <div class="form-row">
                        <div class="form-group">
                            <label>Fetch Top N</label>
                            <select name="fetch_top_n">
                                <option value="3">3 results</option>
                                <option value="5" selected>5 results</option>
                                <option value="10">10 results</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label>Time Range</label>
                            <select name="time_range">
                                <option value="">All Time</option>
                                <option value="day">Past Day</option>
                                <option value="week">Past Week</option>
                                <option value="month">Past Month</option>
                            </select>
                        </div>
                    </div>
                    <button type="submit" class="btn btn-primary">🔗 Search & Fetch</button>
                </form>
            </div>
            
            <!-- Deep Research Tool -->
            <div class="tool-card">
                <h3><span class="icon">🧠</span> Deep Research</h3>
                <p class="description">Multi-query research - processes multiple queries in parallel</p>
                <form id="deepResearchForm">
                    <div class="form-group">
                        <label>Research Queries (one per line)</label>
                        <textarea name="queries" rows="3" placeholder="What is quantum computing?\\nQuantum computing applications\\nQuantum vs classical computing" required></textarea>
                    </div>
                    <div class="form-row">
                        <div class="form-group">
                            <label>Fetch Per Query</label>
                            <select name="fetch_top_n">
                                <option value="2">2 results</option>
                                <option value="3" selected>3 results</option>
                                <option value="5">5 results</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label>Max Content (chars)</label>
                            <input type="number" name="max_content_length" value="5000" min="1000" max="50000">
                        </div>
                    </div>
                    <button type="submit" class="btn btn-primary">🧠 Research</button>
                </form>
            </div>
            
            <!-- Crawl Site Tool -->
            <div class="tool-card">
                <h3><span class="icon">🕷️</span> Crawl Website</h3>
                <p class="description">Recursively crawl websites and extract content from multiple pages</p>
                <form id="crawlForm">
                    <div class="form-group">
                        <label>Website URL</label>
                        <input type="url" name="url" placeholder="https://example.com" required>
                    </div>
                    <div class="form-row">
                        <div class="form-group">
                            <label>Max Pages</label>
                            <input type="number" name="max_pages" value="10" min="1" max="100">
                        </div>
                        <div class="form-group">
                            <label>Max Depth</label>
                            <input type="number" name="max_depth" value="2" min="1" max="5">
                        </div>
                    </div>
                    <div class="form-group">
                        <label>Output Format</label>
                        <select name="output_format">
                            <option value="markdown">Markdown</option>
                            <option value="text">Plain Text</option>
                            <option value="html">HTML</option>
                        </select>
                    </div>
                    <button type="submit" class="btn btn-primary">🕷️ Start Crawl</button>
                </form>
            </div>
            
            <!-- YouTube Transcript Tool -->
            <div class="tool-card">
                <h3><span class="icon">🎬</span> YouTube Transcript</h3>
                <p class="description">Extract transcripts from YouTube videos with language support</p>
                <form id="ytTranscriptForm">
                    <div class="form-group">
                        <label>YouTube URL or Video ID</label>
                        <input type="text" name="video" placeholder="https://youtube.com/watch?v=... or video ID" required>
                    </div>
                    <div class="form-row">
                        <div class="form-group">
                            <label>Format</label>
                            <select name="format">
                                <option value="text">Plain Text</option>
                                <option value="json">JSON (with timestamps)</option>
                                <option value="srt">SRT Subtitles</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label>Language (optional)</label>
                            <input type="text" name="lang" placeholder="auto-detect, or: en, es, hi...">
                        </div>
                    </div>
                    <div class="form-row">
                        <div class="form-group">
                            <label>Start Time (sec)</label>
                            <input type="number" name="start" placeholder="0" min="0">
                        </div>
                        <div class="form-group">
                            <label>End Time (sec)</label>
                            <input type="number" name="end" placeholder="End" min="0">
                        </div>
                    </div>
                    <button type="submit" class="btn btn-primary">🎬 Get Transcript</button>
                </form>
            </div>
        </div>
        
        <!-- Results Section -->
        <div class="result-section" id="resultSection" style="display: none;">
            <h2>📋 Results</h2>
            <div class="stats" id="statsSection" style="display: none;"></div>
            <div class="result-box" id="resultBox"></div>
        </div>
        
        <!-- Quick Links -->
        <div class="quick-links">
            <a href="/docs" target="_blank">📚 API Documentation</a>
            <a href="/health" target="_blank">💚 Health Check</a>
            <a href="https://github.com/ankushthakur08/miyami_websearch_tool" target="_blank">⭐ GitHub</a>
        </div>
    </div>
    
    <script>
        const resultSection = document.getElementById('resultSection');
        const resultBox = document.getElementById('resultBox');
        const statsSection = document.getElementById('statsSection');
        
        function showLoading(message = 'Processing...') {
            resultSection.style.display = 'block';
            statsSection.style.display = 'none';
            resultBox.innerHTML = '<div class="loading"><span class="loading-spinner"></span> ' + message + '</div>';
            resultBox.className = 'result-box loading';
            resultSection.scrollIntoView({ behavior: 'smooth' });
        }
        
        function showResult(data, stats = null) {
            resultBox.className = 'result-box';
            
            if (stats) {
                statsSection.style.display = 'grid';
                statsSection.innerHTML = Object.entries(stats).map(([label, value]) => 
                    `<div class="stat-item"><div class="value">${value}</div><div class="label">${label}</div></div>`
                ).join('');
            } else {
                statsSection.style.display = 'none';
            }
            
            if (typeof data === 'object') {
                resultBox.innerHTML = '<span class="success">' + JSON.stringify(data, null, 2) + '</span>';
            } else {
                resultBox.innerHTML = '<span class="success">' + escapeHtml(data) + '</span>';
            }
        }
        
        function showError(error) {
            resultBox.className = 'result-box';
            statsSection.style.display = 'none';
            resultBox.innerHTML = '<span class="error">❌ Error: ' + escapeHtml(error) + '</span>';
        }
        
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        async function submitForm(form, endpoint, buildParams) {
            const formData = new FormData(form);
            const params = buildParams(formData);
            const url = endpoint + '?' + new URLSearchParams(params).toString();
            
            try {
                showLoading('Fetching results...');
                const response = await fetch(url);
                const data = await response.json();
                
                if (!response.ok) {
                    let errorMsg = data.detail || 'Request failed';
                    if (typeof errorMsg === 'object') {
                        errorMsg = JSON.stringify(errorMsg, null, 2);
                    }
                    throw new Error(errorMsg);
                }
                
                // Extract stats based on endpoint type
                let stats = null;
                if (data.total_results !== undefined) {
                    stats = { 'Results': data.total_results };
                    if (data.query) stats['Query'] = data.query;
                }
                if (data.word_count !== undefined) {
                    stats = stats || {};
                    stats['Words'] = data.word_count;
                }
                if (data.segment_count !== undefined) {
                    stats = stats || {};
                    stats['Segments'] = data.segment_count;
                    stats['Duration'] = (data.total_duration || 0).toFixed(1) + 's';
                }
                if (data.pages_crawled !== undefined) {
                    stats = { 'Pages': data.pages_crawled, 'Duration': data.crawl_duration };
                }
                
                showResult(data, stats);
            } catch (error) {
                showError(error.message);
            }
        }
        
        // Search Form
        document.getElementById('searchForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            await submitForm(e.target, '/search-api', (fd) => {
                const params = { query: fd.get('query') };
                if (fd.get('time_range')) params.time_range = fd.get('time_range');
                if (fd.get('categories')) params.categories = fd.get('categories');
                if (fd.get('rerank')) params.rerank = 'true';
                return params;
            });
        });
        
        // Fetch Form
        document.getElementById('fetchForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            await submitForm(e.target, '/fetch', (fd) => {
                const params = { 
                    url: fd.get('url'),
                    format: fd.get('output_format'),
                    stealth_mode: fd.get('stealth_mode')
                };
                if (fd.get('auto_bypass')) params.auto_bypass = 'true';
                return params;
            });
        });
        
        // Search & Fetch Form
        document.getElementById('searchFetchForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            await submitForm(e.target, '/search-and-fetch', (fd) => {
                const params = { 
                    query: fd.get('query'),
                    fetch_top_n: fd.get('fetch_top_n')
                };
                if (fd.get('time_range')) params.time_range = fd.get('time_range');
                return params;
            });
        });
        
        // Deep Research Form
        document.getElementById('deepResearchForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            showLoading('Researching multiple queries... This may take a while.');
            const formData = new FormData(e.target);
            const queries = formData.get('queries').split('\\n').filter(q => q.trim());
            const url = '/deep-research?' + new URLSearchParams({
                queries: queries.join(','),
                fetch_top_n: formData.get('fetch_top_n'),
                max_content_length: formData.get('max_content_length')
            }).toString();
            
            try {
                const response = await fetch(url);
                const data = await response.json();
                if (!response.ok) throw new Error(data.detail || 'Request failed');
                showResult(data, { 'Queries': data.query_count, 'Results': data.total_results });
            } catch (error) {
                showError(error.message);
            }
        });
        
        // Crawl Form
        document.getElementById('crawlForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            showLoading('Crawling website... This may take several minutes.');
            await submitForm(e.target, '/crawl-site', (fd) => ({
                start_url: fd.get('url'),
                max_pages: fd.get('max_pages'),
                max_depth: fd.get('max_depth'),
                format: fd.get('output_format')
            }));
        });
        
        // YouTube Transcript Form
        document.getElementById('ytTranscriptForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            await submitForm(e.target, '/yt-transcript', (fd) => {
                const params = { 
                    video: fd.get('video'),
                    format: fd.get('format')
                };
                if (fd.get('lang')) params.lang = fd.get('lang');
                if (fd.get('start')) params.start = fd.get('start');
                if (fd.get('end')) params.end = fd.get('end');
                return params;
            });
        });
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the interactive GUI for the API"""
    return GUI_HTML

@app.get("/api")
async def api_info():
    """Return API info as JSON (for programmatic access)"""
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
    format: str = Query("json", description="Response format (json)"),
    categories: Optional[str] = Query(None, description="Search categories (general, images, videos, etc.)"),
    engines: Optional[str] = Query(None, description="Specific engines to use"),
    language: Optional[str] = Query("en", description="Search language"),
    page: Optional[int] = Query(1, description="Page number"),
    time_range: Optional[str] = Query(None, description="Time filter: day (past 24h), week (past week), month (past month), year (past year)"),
    rerank: bool = Query(False, description="Rerank results using AI for better relevance")
):
    """
    Search using SearXNG and return JSON results with optional time filtering and AI reranking
    
    Time Range Options:
    - day: Results from the past 24 hours
    - week: Results from the past week
    - month: Results from the past month
    - year: Results from the past year
    - None: All results (default)
    
    Example: /search-api?query=AI+news&categories=general&time_range=day&rerank=true
    """
    # Check cache first
    cache_key = f"search:{query}:{categories}:{engines}:{language}:{page}:{time_range}:{rerank}"
    cached_result = cache.get(cache_key)
    if cached_result:
        return JSONResponse(content=cached_result)

    try:
        params = {
            "q": query,
            "format": "json",
            "language": language,
            "pageno": page
        }
        
        if categories:
            params["categories"] = categories
        if engines:
            params["engines"] = engines
        
        # Add time range filter if specified
        if time_range:
            valid_ranges = ["day", "week", "month", "year"]
            if time_range.lower() in valid_ranges:
                params["time_range"] = time_range.lower()
            else:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Invalid time_range. Must be one of: {', '.join(valid_ranges)}"
                )
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"{SEARXNG_URL}/search", params=params)
            response.raise_for_status()
            
            data = response.json()
            
            # Clean and format the response
            results = {
                "query": data.get("query", query),
                "number_of_results": data.get("number_of_results", 0),
                "results": [],
                "suggestions": data.get("suggestions", []),
                "infoboxes": data.get("infoboxes", [])
            }
            
            for result in data.get("results", []):
                clean_result = {
                    "title": result.get("title", ""),
                    "url": result.get("url", ""),
                    "content": result.get("content", ""),
                    "engine": result.get("engine", ""),
                    "parsed_url": result.get("parsed_url", []),
                    "score": result.get("score", 0),
                }
                
                # Add optional fields if they exist
                if "img_src" in result:
                    clean_result["img_src"] = result["img_src"]
                if "thumbnail" in result:
                    clean_result["thumbnail"] = result["thumbnail"]
                if "publishedDate" in result:
                    clean_result["publishedDate"] = result["publishedDate"]
                
                results["results"].append(clean_result)
            
            # Rerank if requested
            if rerank and results["results"]:
                try:
                    ranker = get_ranker()
                    rerank_request = RerankRequest(query=query, passages=[
                        {"id": i, "text": f"{r['title']} {r['content']}", "meta": r} 
                        for i, r in enumerate(results["results"])
                    ])
                    ranked_results = ranker.rerank(rerank_request)
                    # Update results with ranked order
                    results["results"] = [r["meta"] for r in ranked_results]
                except Exception as e:
                    print(f"Reranking failed: {e}")
            
            # Cache the result (expire in 1 hour)
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
    extraction_mode: str = Query("trafilatura", description="Extraction engine: trafilatura (best) or readability (fast)"),
    # Stealth mode (FREE - no API keys needed)
    stealth_mode: str = Query("off", description="Stealth mode: off, low, medium, high (FREE anti-bot bypass)"),
    auto_bypass: bool = Query(False, description="Automatically try higher stealth levels if blocked")
):
    """
    Fetch a URL and return cleaned, structured content (Firecrawl-like quality)
    
    Supports multiple extraction engines:
    - trafilatura: Better accuracy, extracts metadata, dates, authors
    - readability: Faster, good for simple articles
    
    Output formats:
    - text: Clean plain text
    - markdown: Structured markdown (Firecrawl-like)
    - html: Clean HTML
    
    Stealth Mode (FREE - no API keys needed):
    - off: Standard fetch
    - low: Basic User-Agent rotation
    - medium: UA + header randomization  
    - high: UA + headers + TLS fingerprint (requires curl_cffi package)
    - auto_bypass: Automatically escalate stealth levels if blocked
    
    Example: /fetch?url=https://example.com&format=markdown&stealth_mode=medium
    Example: /fetch?url=https://protected-site.com&stealth_mode=high&auto_bypass=true
    """
    try:
        # Validate URL
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            raise HTTPException(status_code=400, detail="Invalid URL format")
        
        # Validate stealth_mode
        valid_stealth_modes = ["off", "low", "medium", "high"]
        if stealth_mode.lower() not in valid_stealth_modes:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid stealth_mode. Must be one of: {', '.join(valid_stealth_modes)}"
            )
        
        # Use advanced_fetch for the actual fetching (FREE - no API keys needed)
        fetch_result = await advanced_fetch(
            url=url,
            stealth_mode=stealth_mode,
            auto_bypass=auto_bypass
        )
        
        html_content = fetch_result["html"]
        final_url = fetch_result["final_url"]
        status_code = fetch_result["status_code"]
        fetch_method = fetch_result["fetch_method"]
        protection_info = fetch_result["protection_info"]
        
        # Initialize result structure
        result = {
            "success": True,
            "url": final_url,
            "status_code": status_code,
            "fetch_method": fetch_method,
        }
        
        # Add protection info if detected
        if protection_info:
            result["protection_info"] = protection_info
        
        # Use trafilatura for better extraction (Firecrawl-like)
        if extraction_mode == "trafilatura":
            # Extract with trafilatura (best quality)
            extracted = trafilatura.extract(
                html_content,
                include_comments=False,
                include_tables=True,
                include_images=include_images,
                include_links=include_links,
                output_format='json',
                url=final_url,
                with_metadata=True
            )
            
            if extracted:
                data = json.loads(extracted)
                
                # Build comprehensive metadata
                metadata = {
                    "title": data.get("title", ""),
                    "author": data.get("author", ""),
                    "sitename": data.get("sitename", ""),
                    "date": data.get("date", ""),
                    "categories": data.get("categories", []),
                    "tags": data.get("tags", []),
                    "description": data.get("description", ""),
                    "language": data.get("language", ""),
                    "url": final_url,
                }
                
                # Clean empty values
                metadata = {k: v for k, v in metadata.items() if v}
                result["metadata"] = metadata
                
                # Get main text
                main_text = data.get("text", "")
                
                # Format output based on requested format
                if format == "markdown":
                    # Use trafilatura's markdown output
                    markdown_content = trafilatura.extract(
                        html_content,
                        include_comments=False,
                        include_tables=True,
                        include_images=include_images,
                        include_links=include_links,
                        output_format='markdown',
                        url=final_url
                    )
                    result["content"] = markdown_content or main_text
                        
                elif format == "html":
                    # Return clean HTML
                    result["content"] = data.get("raw_text", main_text)
                else:
                    # Plain text (default)
                    result["content"] = main_text
                
                # Limit content length
                if len(result["content"]) > max_content_length:
                    result["content"] = result["content"][:max_content_length] + "\n\n... [truncated]"
                
            else:
                # Fallback to readability if trafilatura fails
                extraction_mode = "readability"
        
        # Readability extraction (fallback or explicit)
        if extraction_mode == "readability":
            doc = Document(html_content)
            soup = BeautifulSoup(html_content, 'lxml')
            
            # Extract enhanced metadata
            metadata = {
                "title": doc.title(),
                "url": final_url,
                "status_code": status_code,
            }
            
            # Extract more metadata
            for meta in soup.find_all("meta"):
                name = meta.get("name", "").lower() or meta.get("property", "").lower()
                content = meta.get("content", "")
                
                if "description" in name and content:
                    metadata["description"] = content
                elif "author" in name and content:
                    metadata["author"] = content
                elif "keywords" in name and content:
                    metadata["keywords"] = content
                elif "published" in name or "article:published" in name:
                    metadata["published_date"] = content
                elif "site_name" in name or "og:site_name" in name:
                    metadata["sitename"] = content
            
            result["metadata"] = metadata
            
            # Extract main content
            article_html = doc.summary()
            article_soup = BeautifulSoup(article_html, 'lxml')
            
            if format == "markdown":
                # Convert to markdown
                h = html2text.HTML2Text()
                h.ignore_links = not include_links
                h.ignore_images = not include_images
                h.body_width = 0
                result["content"] = h.handle(article_html)
            elif format == "html":
                result["content"] = article_html
            else:
                # Clean text
                main_text = article_soup.get_text(separator="\n", strip=True)
                # Remove excessive newlines
                main_text = re.sub(r'\n{3,}', '\n\n', main_text)
                result["content"] = main_text
            
            # Limit content length
            if len(result["content"]) > max_content_length:
                result["content"] = result["content"][:max_content_length] + "\n\n... [truncated]"
            
            # Extract headings structure
            headings = []
            for heading in article_soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
                text = heading.get_text(strip=True)
                if text:
                    headings.append({
                        "level": heading.name,
                        "text": text
                    })
            result["headings"] = headings
            
            # Extract links if requested
            if include_links:
                links = []
                for link in article_soup.find_all('a', href=True):
                    href = link['href']
                    text = link.get_text(strip=True)
                    if text and href:
                        absolute_url = urljoin(final_url, href)
                        links.append({
                            "text": text,
                            "url": absolute_url
                        })
                result["links"] = links[:100]  # Limit to 100 links
            
            # Extract images if requested
            if include_images:
                images = []
                for img in article_soup.find_all('img'):
                    src = img.get('src') or img.get('data-src')
                    if src:
                        img_url = urljoin(final_url, src)
                        images.append({
                            "url": img_url,
                            "alt": img.get('alt', ''),
                            "title": img.get('title', '')
                        })
                result["images"] = images[:50]  # Limit to 50 images
        
        # Add content statistics
        result["stats"] = {
            "content_length": len(result["content"]),
            "word_count": len(result["content"].split()),
            "extraction_mode": extraction_mode,
            "format": format,
            "fetch_method": fetch_method
        }
        
        return JSONResponse(content=result)
            
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"Failed to fetch URL: {str(e)}")
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"Cannot connect to URL: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing content: {str(e)}")

@app.get("/search-and-fetch")
async def search_and_fetch(
    query: str = Query(..., description="Search query"),
    num_results: int = Query(3, description="Number of results to fetch (1-5)", ge=1, le=5),
    categories: Optional[str] = Query("general", description="Search categories"),
    language: Optional[str] = Query("en", description="Search language"),
    format: str = Query("markdown", description="Output format: text, markdown, or html"),
    max_content_length: int = Query(100000, description="Maximum content length per page"),
    time_range: Optional[str] = Query(None, description="Time filter: day, week, month, year"),
    rerank: bool = Query(False, description="Rerank results using AI for better relevance"),
    # Stealth mode (FREE - no API keys needed)
    stealth_mode: str = Query("off", description="Stealth mode: off, low, medium, high (FREE anti-bot bypass)"),
    auto_bypass: bool = Query(False, description="Automatically try higher stealth levels if blocked")
):
    """
    Search and automatically fetch full content from top N results (Enhanced with Trafilatura)
    
    This is a convenience endpoint that:
    1. Searches for your query (with optional time filter)
    2. Gets top N results (default: 3, max: 5)
    3. Fetches full webpage content using advanced extraction
    4. Returns both search snippets AND full content (markdown/text/html)
    
    Time Range Options:
    - day: Results from the past 24 hours
    - week: Results from the past week
    - month: Results from the past month
    - year: Results from the past year
    
    Stealth Mode (FREE - no API keys needed):
    - off: Standard fetch
    - low/medium/high: Progressive anti-bot bypass
    - auto_bypass: Automatically escalate stealth levels if blocked
    
    Example: /search-and-fetch?query=AI+news&num_results=3&format=markdown&time_range=day
    Example: /search-and-fetch?query=protected+site&stealth_mode=high&auto_bypass=true
    """
    # Check cache (include stealth params in key)
    cache_key = f"search_fetch:{query}:{num_results}:{categories}:{language}:{format}:{time_range}:{rerank}:{stealth_mode}"
    cached_result = cache.get(cache_key)
    if cached_result:
        return JSONResponse(content=cached_result)

    try:
        # Step 1: Perform search
        search_params = {
            "q": query,
            "format": "json",
            "language": language,
            "pageno": 1
        }
        
        if categories:
            search_params["categories"] = categories
        
        # Add time range filter if specified
        if time_range:
            valid_ranges = ["day", "week", "month", "year"]
            if time_range.lower() in valid_ranges:
                search_params["time_range"] = time_range.lower()
            else:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Invalid time_range. Must be one of: {', '.join(valid_ranges)}"
                )
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            search_response = await client.get(f"{SEARXNG_URL}/search", params=search_params)
            search_response.raise_for_status()
            search_data = search_response.json()
        
        # Get top N results
        all_results = search_data.get("results", [])
        
        # Rerank if requested
        if rerank and all_results:
            try:
                ranker = get_ranker()
                rerank_request = RerankRequest(query=query, passages=[
                    {"id": i, "text": f"{r.get('title', '')} {r.get('content', '')}", "meta": r} 
                    for i, r in enumerate(all_results)
                ])
                ranked_results = ranker.rerank(rerank_request)
                all_results = [r["meta"] for r in ranked_results]
            except Exception as e:
                print(f"Reranking failed: {e}")
        
        top_results = all_results[:num_results]
        
        if not top_results:
            return JSONResponse(content={
                "query": query,
                "num_results_found": 0,
                "results": [],
                "message": "No search results found"
            })
        
        # Step 2: Fetch content from each URL in parallel
        async def fetch_single_url(result: dict) -> dict:
            """Fetch content for a single search result using enhanced extraction"""
            url = result.get("url", "")
            
            # Validate URL
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                return {
                    "search_result": result,
                    "fetch_status": "error",
                    "fetch_error": "Invalid URL format",
                    "content": None
                }
            
            try:
                # Use advanced_fetch for stealth mode (FREE - no API keys needed)
                fetch_result = await advanced_fetch(
                    url=url,
                    stealth_mode=stealth_mode,
                    auto_bypass=auto_bypass
                )
                
                html_content = fetch_result["html"]
                final_url = fetch_result["final_url"]
                fetch_method = fetch_result["fetch_method"]
                protection_info = fetch_result["protection_info"]
                
                # Use trafilatura for better extraction
                extracted = trafilatura.extract(
                    html_content,
                    include_comments=False,
                    include_tables=True,
                    include_images=True,
                    include_links=True,
                    output_format='json',
                    url=final_url,
                    with_metadata=True
                )
                
                if extracted:
                    data = json.loads(extracted)
                    
                    # Get content in requested format
                    if format == "markdown":
                        content = trafilatura.extract(
                            html_content,
                            include_comments=False,
                            include_tables=True,
                            output_format='markdown',
                            url=final_url
                        ) or data.get("text", "")
                    elif format == "html":
                        content = data.get("raw_text", data.get("text", ""))
                    else:
                        content = data.get("text", "")
                    
                    # Limit content length
                    if len(content) > max_content_length:
                        content = content[:max_content_length] + "\n\n... [truncated]"
                    
                    fetch_result_data = {
                        "search_result": {
                            "title": result.get("title", ""),
                            "url": final_url,
                            "snippet": result.get("content", ""),
                            "engine": result.get("engine", ""),
                            "score": result.get("score", 0)
                        },
                        "fetch_status": "success",
                        "fetch_method": fetch_method,
                        "fetched_content": {
                            "title": data.get("title", result.get("title", "")),
                            "author": data.get("author", ""),
                            "date": data.get("date", ""),
                            "sitename": data.get("sitename", ""),
                            "content": content,
                            "word_count": len(content.split()),
                            "format": format
                        }
                    }
                    
                    # Add protection info if detected
                    if protection_info:
                        fetch_result_data["protection_info"] = protection_info
                    
                    return fetch_result_data
                else:
                    # Fallback to readability
                    doc = Document(html_content)
                    article_html = doc.summary()
                    
                    if format == "markdown":
                        h = html2text.HTML2Text()
                        h.body_width = 0
                        content = h.handle(article_html)
                    elif format == "html":
                        content = article_html
                    else:
                        article_soup = BeautifulSoup(article_html, 'lxml')
                        content = article_soup.get_text(separator="\n", strip=True)
                        content = re.sub(r'\n{3,}', '\n\n', content)
                    
                    # Limit content length
                    if len(content) > max_content_length:
                        content = content[:max_content_length] + "\n\n... [truncated]"
                    
                    fetch_result_data = {
                        "search_result": {
                            "title": result.get("title", ""),
                            "url": final_url,
                            "snippet": result.get("content", ""),
                            "engine": result.get("engine", ""),
                            "score": result.get("score", 0)
                        },
                        "fetch_status": "success",
                        "fetch_method": fetch_method,
                        "fetched_content": {
                            "title": doc.title(),
                            "content": content,
                            "word_count": len(content.split()),
                            "format": format
                        }
                    }
                    
                    # Add protection info if detected
                    if protection_info:
                        fetch_result_data["protection_info"] = protection_info
                    
                    return fetch_result_data
                    
            except HTTPException as e:
                return {
                    "search_result": result,
                    "fetch_status": "error",
                    "fetch_error": e.detail,
                    "content": None
                }
            except Exception as e:
                return {
                    "search_result": result,
                    "fetch_status": "error",
                    "fetch_error": f"Processing error: {str(e)}",
                    "content": None
                }
        
        # Fetch all URLs in parallel
        fetch_tasks = [fetch_single_url(result) for result in top_results]
        fetched_results = await asyncio.gather(*fetch_tasks)
        
        # Count successes and failures
        successful_fetches = sum(1 for r in fetched_results if r["fetch_status"] == "success")
        failed_fetches = sum(1 for r in fetched_results if r["fetch_status"] == "error")
        
        final_response = {
            "query": query,
            "num_results_requested": num_results,
            "num_results_found": len(top_results),
            "successful_fetches": successful_fetches,
            "failed_fetches": failed_fetches,
            "fetch_options": {
                "stealth_mode": stealth_mode,
                "auto_bypass": auto_bypass
            },
            "results": fetched_results,
            "suggestions": search_data.get("suggestions", [])
        }
        
        # Cache result
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
    queries: str = Query(..., description="Comma-separated list of research queries (e.g., 'AI trends,machine learning basics,neural networks')"),
    breadth: int = Query(3, description="Number of results to fetch per query (1-5)", ge=1, le=5),
    time_range: Optional[str] = Query(None, description="Time filter: day, week, month, year"),
    max_content_length: int = Query(30000, description="Max content length per result"),
    include_suggestions: bool = Query(True, description="Include search suggestions in output"),
    # Stealth mode (FREE - no API keys needed)
    stealth_mode: str = Query("off", description="Stealth mode: off, low, medium, high (FREE anti-bot bypass)"),
    auto_bypass: bool = Query(False, description="Automatically try higher stealth levels if blocked")
):
    """
    Perform comprehensive research across multiple queries and compile into a unified report.
    
    Workflow:
    1. Parse multiple queries (comma-separated)
    2. For each query, search and fetch top N results (breadth)
    3. Process all queries in parallel for speed
    4. Compile all results into one detailed, well-formatted response
    
    Stealth Mode (FREE - no API keys needed):
    - off: Standard fetch
    - low/medium/high: Progressive anti-bot bypass
    - auto_bypass: Automatically escalate stealth levels if blocked
    
    Example: /deep-research?queries=AI+trends,machine+learning+2024,GPT+applications&breadth=3&time_range=month
    Example: /deep-research?queries=protected+sites&stealth_mode=high&auto_bypass=true
    
    Response includes:
    - Summary statistics
    - Per-query research results with full content
    - Compiled markdown report
    - All suggestions for further research
    """
    # Parse queries
    query_list = [q.strip() for q in queries.split(",") if q.strip()]
    
    if not query_list:
        raise HTTPException(status_code=400, detail="No valid queries provided. Use comma-separated queries.")
    
    if len(query_list) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 queries allowed per request.")
    
    # Validate stealth_mode
    valid_stealth_modes = ["off", "low", "medium", "high"]
    if stealth_mode.lower() not in valid_stealth_modes:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid stealth_mode. Must be one of: {', '.join(valid_stealth_modes)}"
        )
    
    # Check cache
    cache_key = f"deep_research:{','.join(sorted(query_list))}:{breadth}:{time_range}:{max_content_length}:{stealth_mode}"
    cached_result = cache.get(cache_key)
    if cached_result:
        return JSONResponse(content=cached_result)
    
    try:
        # Process all queries in parallel
        async def process_single_query(query: str) -> dict:
            """Process a single query and return structured results"""
            try:
                result = await search_and_fetch(
                    query=query,
                    num_results=breadth,
                    time_range=time_range,
                    format="markdown",
                    max_content_length=max_content_length,
                    categories="general",
                    language="en",
                    rerank=True,
                    stealth_mode=stealth_mode,
                    auto_bypass=auto_bypass
                )
                
                # Parse JSONResponse
                data = json.loads(result.body.decode())
                
                return {
                    "query": query,
                    "status": "success",
                    "num_results": data.get("num_results_found", 0),
                    "successful_fetches": data.get("successful_fetches", 0),
                    "results": data.get("results", []),
                    "suggestions": data.get("suggestions", []),
                    "fetch_options": data.get("fetch_options", {})
                }
            except Exception as e:
                return {
                    "query": query,
                    "status": "error",
                    "error": str(e),
                    "num_results": 0,
                    "results": [],
                    "suggestions": []
                }
        
        # Execute all queries in parallel
        query_tasks = [process_single_query(q) for q in query_list]
        query_results = await asyncio.gather(*query_tasks)
        
        # Compile statistics
        total_results = sum(r["num_results"] for r in query_results)
        total_successful = sum(r["successful_fetches"] for r in query_results if r["status"] == "success")
        successful_queries = sum(1 for r in query_results if r["status"] == "success")
        failed_queries = sum(1 for r in query_results if r["status"] == "error")
        
        # Collect all suggestions
        all_suggestions = []
        for r in query_results:
            all_suggestions.extend(r.get("suggestions", []))
        unique_suggestions = list(set(all_suggestions))[:20]  # Dedupe and limit
        
        # Generate compiled markdown report
        compiled_report = _generate_compiled_report(query_list, query_results)
        
        # Build final response
        final_response = {
            "research_summary": {
                "total_queries": len(query_list),
                "successful_queries": successful_queries,
                "failed_queries": failed_queries,
                "total_results_found": total_results,
                "total_successful_fetches": total_successful,
                "time_range_filter": time_range,
                "breadth_per_query": breadth,
                "fetch_options": {
                    "stealth_mode": stealth_mode,
                    "auto_bypass": auto_bypass
                }
            },
            "queries": query_list,
            "query_results": query_results,
            "compiled_report": compiled_report,
            "all_suggestions": unique_suggestions if include_suggestions else []
        }
        
        # Cache result (30 minutes for deep research)
        cache.set(cache_key, final_response, expire=1800)
        
        return JSONResponse(content=final_response)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Deep research failed: {str(e)}")


def _generate_compiled_report(queries: List[str], results: List[dict]) -> str:
    """Generate a compiled markdown report from all query results"""
    
    report_lines = [
        "# Deep Research Report",
        "",
        f"**Queries Researched:** {len(queries)}",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "---",
        ""
    ]
    
    for i, result in enumerate(results, 1):
        query = result.get("query", "Unknown")
        report_lines.append(f"## {i}. {query}")
        report_lines.append("")
        
        if result.get("status") == "error":
            report_lines.append(f"⚠️ **Error:** {result.get('error', 'Unknown error')}")
            report_lines.append("")
            continue
        
        fetched_results = result.get("results", [])
        if not fetched_results:
            report_lines.append("*No results found for this query.*")
            report_lines.append("")
            continue
        
        for j, res in enumerate(fetched_results, 1):
            search_result = res.get("search_result", {})
            fetched_content = res.get("fetched_content", {})
            
            title = fetched_content.get("title") or search_result.get("title", "Untitled")
            url = search_result.get("url", "")
            author = fetched_content.get("author", "")
            date = fetched_content.get("date", "")
            sitename = fetched_content.get("sitename", "")
            content = fetched_content.get("content", "")
            
            report_lines.append(f"### {i}.{j} {title}")
            report_lines.append("")
            
            # Metadata line
            meta_parts = []
            if sitename:
                meta_parts.append(f"**Source:** {sitename}")
            if author:
                meta_parts.append(f"**Author:** {author}")
            if date:
                meta_parts.append(f"**Date:** {date}")
            if url:
                meta_parts.append(f"[🔗 Link]({url})")
            
            if meta_parts:
                report_lines.append(" | ".join(meta_parts))
                report_lines.append("")
            
            if res.get("fetch_status") == "success" and content:
                # Truncate content for report readability
                if len(content) > 2000:
                    content = content[:2000] + "\n\n*[Content truncated for report...]*"
                report_lines.append(content)
            elif res.get("fetch_status") == "error":
                report_lines.append(f"*Failed to fetch: {res.get('fetch_error', 'Unknown error')}*")
            else:
                snippet = search_result.get("snippet", "No content available.")
                report_lines.append(snippet)
            
            report_lines.append("")
            report_lines.append("---")
            report_lines.append("")
    
    return "\n".join(report_lines)

@app.get("/crawl-site")
async def crawl_site(
    start_url: str = Query(..., description="Starting URL to crawl"),
    max_pages: int = Query(50, description="Maximum number of pages to crawl (1-200)", ge=1, le=200),
    max_depth: int = Query(2, description="Maximum crawl depth (0-5)", ge=0, le=5),
    format: str = Query("markdown", description="Output format: text, markdown, or html"),
    include_links: bool = Query(True, description="Include extracted links"),
    include_images: bool = Query(True, description="Include extracted images"),
    url_patterns: Optional[str] = Query(None, description="Comma-separated regex patterns to include URLs (e.g., '/blog/,/docs/')"),
    exclude_patterns: Optional[str] = Query(None, description="Comma-separated regex patterns to exclude URLs"),
    stealth_mode: str = Query("off", description="Stealth mode: off, low, medium, high (applies to all requests)"),
    obey_robots: bool = Query(True, description="Obey robots.txt rules (set to False to bypass)"),
):
    """
    Crawl an entire website and extract content from multiple pages.
    
    This endpoint uses Scrapy to perform site-wide crawling:
    - Starts from a given URL
    - Follows internal links up to max_depth
    - Extracts content using Trafilatura (same as /fetch)
    - Returns all discovered pages with their content
    
    Features:
    - Depth control: Limit how many link-hops from start_url
    - URL filtering: Include/exclude specific URL patterns
    - Polite crawling: Respects robots.txt and rate limits
    - Stealth mode: Anti-bot bypass for all requests
    
    Use Cases:
    - Crawl documentation sites (e.g., docs.python.org)
    - Extract all blog posts from a blog
    - Build knowledge bases from websites
    - Archive entire sections of websites
    
    Example: /crawl-site?start_url=https://example.com/blog&max_pages=20&max_depth=2&url_patterns=/blog/
    
    Note: This is a long-running operation. For 50+ pages, it may take several minutes.
    """
    from urllib.parse import urlparse
    
    # Validate URL
    parsed = urlparse(start_url)
    if not parsed.scheme or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Invalid URL format")
    
    # Validate stealth_mode
    valid_stealth_modes = ["off", "low", "medium", "high"]
    if stealth_mode.lower() not in valid_stealth_modes:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid stealth_mode. Must be one of: {', '.join(valid_stealth_modes)}"
        )
    
    # Parse URL patterns
    url_pattern_list = None
    if url_patterns:
        url_pattern_list = [p.strip() for p in url_patterns.split(",") if p.strip()]
    
    exclude_pattern_list = None
    if exclude_patterns:
        exclude_pattern_list = [p.strip() for p in exclude_patterns.split(",") if p.strip()]
    
    # Check cache
    cache_key = f"crawl:{start_url}:{max_pages}:{max_depth}:{format}:{url_patterns}:{exclude_patterns}:{stealth_mode}:{obey_robots}"
    cached_result = cache.get(cache_key)
    if cached_result:
        return JSONResponse(content=cached_result)
    
    try:
        # Import spider
        from scrapy_crawler import SiteCrawlerSpider
        import subprocess
        import json as json_lib
        import os as os_lib
        import uuid
        
        # Create temp file for results (use a fixed path for debugging)
        results_filename = f"/tmp/scrapy_results_{uuid.uuid4().hex}.json"
        
        # Build scrapy command - simplified approach using -o flag
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
            '-o', results_filename,  # Output file
            '-s', 'LOG_LEVEL=INFO',
            '-s', f'ROBOTSTXT_OBEY={str(obey_robots)}',
            '-s', 'CONCURRENT_REQUESTS=8',
            '-s', 'DOWNLOAD_DELAY=1',
            '-s', 'AUTOTHROTTLE_ENABLED=True',
        ]
        
        # Add stealth middleware if enabled
        # Note: Stealth mode is passed to spider but middleware integration requires proper Scrapy project setup
        # For now, stealth_mode is used as a flag for the spider to adjust behavior
        if stealth_mode != "off":
            cmd.extend([
                '-s', f'STEALTH_MODE={stealth_mode}',
            ])
        
        if url_pattern_list:
            cmd.extend(['-a', f'url_patterns={",".join(url_pattern_list)}'])
        if exclude_pattern_list:
            cmd.extend(['-a', f'exclude_patterns={",".join(exclude_pattern_list)}'])
        
        # Run Scrapy in subprocess to avoid reactor conflicts
        process = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=900,  # 15 minute timeout for heavier crawls
            cwd=os.path.dirname(__file__)
        )
        
        # Debug: log the command and output
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Scrapy command: {' '.join(cmd)}")
        logger.info(f"Scrapy return code: {process.returncode}")
        logger.info(f"Scrapy stdout: {process.stdout[:500]}")
        logger.info(f"Scrapy stderr: {process.stderr[:500]}")
        logger.info(f"Results file: {results_filename}")
        logger.info(f"File exists: {os_lib.path.exists(results_filename)}")
        
        # Check for errors
        if process.returncode != 0:
            raise Exception(f"Scrapy failed with code {process.returncode}: {process.stderr}")
        
        # Check if results file exists
        if not os_lib.path.exists(results_filename):
            raise Exception(f"Scrapy did not create results file at {results_filename}. Stdout: {process.stdout[:200]}")
        
        # Read results
        try:
            with open(results_filename, 'r') as f:
                content = f.read()
                if not content or content.strip() == '':
                    raise Exception("Scrapy results file is empty")
                results = json_lib.loads(content)
        except json_lib.JSONDecodeError as e:
            raise Exception(f"Invalid JSON from Scrapy: {e}")
        
        # Clean up temp files
        os_lib.unlink(results_filename)
        
        # Compile response
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
        
        # Cache result (30 minutes)
        cache.set(cache_key, response_data, expire=1800)
        
        return JSONResponse(content=response_data)
        
    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Scrapy dependencies not installed. Run: pip install scrapy crochet. Error: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Crawl failed: {str(e)}")

@app.get("/health")
@app.head("/health")
async def health_check():
    """Check if SearXNG is accessible"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(SEARXNG_URL)
            searxng_status = "up" if response.status_code == 200 else "down"
    except:
        searxng_status = "down"
    
    return {
        "status": "ok",
        "searxng": searxng_status,
        "searxng_url": SEARXNG_URL
    }

@app.head("/")
async def root_head():
    """Handle HEAD requests for health checks"""
    return {}


# ============== YouTube Transcript Endpoint ==============

# YouTube video ID extraction patterns
YOUTUBE_ID_REGEXES = [
    r"(?:v=|/videos/|embed/|shorts/)([\w-]{11})",
    r"youtu\.be/([\w-]{11})",
    r"youtube\.com/watch\?.*v=([\w-]{11})",
    r"^([\w-]{11})$",
]

def extract_video_id(url_or_id: str) -> Optional[str]:
    """Extract YouTube video ID from URL or direct ID."""
    s = url_or_id.strip()
    for pattern in YOUTUBE_ID_REGEXES:
        m = re.search(pattern, s)
        if m:
            return m.group(1)
    if re.fullmatch(r"[\w-]{11}", s):
        return s
    return None


def fetch_transcript_ytdlp(video_id: str, lang: Optional[str] = None) -> dict:
    """
    Fallback transcript fetcher using yt-dlp.
    Better anti-bot handling, works from datacenter IPs.
    Returns dict with 'transcript' (list of segments), 'language', and 'available_langs'.
    """
    import subprocess
    import json
    import tempfile
    import os
    
    url = f"https://www.youtube.com/watch?v={video_id}"
    
    # First, get available subtitles
    try:
        result = subprocess.run(
            ["yt-dlp", "--list-subs", "--skip-download", "-J", url],
            capture_output=True,
            text=True,
            timeout=60
        )
        if result.returncode == 0:
            info = json.loads(result.stdout)
            subtitles = info.get("subtitles", {})
            auto_captions = info.get("automatic_captions", {})
            
            available_langs = []
            for code in subtitles.keys():
                available_langs.append({"code": code, "is_generated": False})
            for code in auto_captions.keys():
                if code not in subtitles:
                    available_langs.append({"code": code, "is_generated": True})
            
            if not available_langs:
                raise Exception("No subtitles available")
    except subprocess.TimeoutExpired:
        raise Exception("Timeout fetching subtitle info")
    except json.JSONDecodeError:
        raise Exception("Failed to parse video info")
    
    # Determine which language to fetch
    target_lang = lang
    is_auto = False
    
    if target_lang:
        # Check if requested language exists
        if target_lang not in subtitles and target_lang not in auto_captions:
            # Try to find a close match
            for code in list(subtitles.keys()) + list(auto_captions.keys()):
                if code.startswith(target_lang) or target_lang.startswith(code.split('-')[0]):
                    target_lang = code
                    break
    else:
        # Auto-detect: prefer manual over auto-generated
        if subtitles:
            target_lang = list(subtitles.keys())[0]
        elif auto_captions:
            target_lang = list(auto_captions.keys())[0]
            is_auto = True
    
    if not target_lang:
        raise Exception("No suitable subtitle track found")
    
    # Download the subtitle
    with tempfile.TemporaryDirectory() as tmpdir:
        sub_file = os.path.join(tmpdir, "sub")
        
        # Build yt-dlp command
        cmd = [
            "yt-dlp",
            "--skip-download",
            "--write-sub" if target_lang in subtitles else "--write-auto-sub",
            "--sub-lang", target_lang,
            "--sub-format", "json3",
            "--convert-subs", "json3",
            "-o", sub_file,
            url
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            raise Exception("Timeout downloading subtitles")
        
        # Find the subtitle file
        sub_files = [f for f in os.listdir(tmpdir) if f.endswith('.json3')]
        if not sub_files:
            # Try vtt format as fallback
            cmd[cmd.index("json3")] = "vtt"
            cmd[cmd.index("json3")] = "vtt"
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            sub_files = [f for f in os.listdir(tmpdir) if '.vtt' in f or '.json' in f]
        
        if not sub_files:
            raise Exception(f"Failed to download subtitles: {result.stderr}")
        
        sub_path = os.path.join(tmpdir, sub_files[0])
        
        with open(sub_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Parse based on format
        transcript = []
        if sub_path.endswith('.json3'):
            try:
                data = json.loads(content)
                events = data.get('events', [])
                for event in events:
                    if 'segs' in event:
                        text = ''.join(seg.get('utf8', '') for seg in event['segs']).strip()
                        if text:
                            transcript.append({
                                'start': event.get('tStartMs', 0) / 1000.0,
                                'duration': (event.get('dDurationMs', 0)) / 1000.0,
                                'text': text
                            })
            except json.JSONDecodeError:
                raise Exception("Failed to parse subtitle file")
        else:
            # Parse VTT format
            import re
            pattern = r'(\d{2}:\d{2}:\d{2}\.\d{3}) --> (\d{2}:\d{2}:\d{2}\.\d{3})\n(.+?)(?=\n\n|$)'
            matches = re.findall(pattern, content, re.DOTALL)
            for start_time, end_time, text in matches:
                def time_to_seconds(t):
                    parts = t.replace(',', '.').split(':')
                    return float(parts[0])*3600 + float(parts[1])*60 + float(parts[2])
                start = time_to_seconds(start_time)
                end = time_to_seconds(end_time)
                clean_text = re.sub(r'<[^>]+>', '', text).strip()
                if clean_text:
                    transcript.append({
                        'start': start,
                        'duration': end - start,
                        'text': clean_text
                    })
        
        return {
            'transcript': transcript,
            'language': target_lang,
            'is_generated': is_auto or target_lang in auto_captions,
            'available_langs': available_langs
        }


@app.get("/yt-transcript")
async def youtube_transcript(
    video: str = Query(..., description="YouTube video URL or 11-character video ID"),
    format: str = Query("text", description="Output format: text, json, or srt"),
    lang: Optional[str] = Query(None, description="Preferred language code (e.g., 'en', 'es', 'hi'). If not specified, auto-detects and fetches first available transcript"),
    translate: Optional[str] = Query(None, description="Translate transcript to target language code"),
    start: Optional[float] = Query(None, description="Start time in seconds to trim transcript"),
    end: Optional[float] = Query(None, description="End time in seconds to trim transcript"),
    list_langs: bool = Query(False, description="List available transcript languages instead of fetching"),
):
    """
    Fetch YouTube video transcripts for LLM consumption.
    
    Features:
    - Accepts YouTube URL or video ID
    - Multiple output formats (text, json, srt)
    - Language selection and translation
    - Time-range slicing
    - Lists available languages
    
    Examples:
    - /yt-transcript?video=dQw4w9WgXcQ&format=text
    - /yt-transcript?video=https://youtube.com/watch?v=dQw4w9WgXcQ&lang=en
    - /yt-transcript?video=dQw4w9WgXcQ&translate=es
    - /yt-transcript?video=dQw4w9WgXcQ&start=60&end=120
    - /yt-transcript?video=dQw4w9WgXcQ&list_langs=true
    """
    # Lazy import to avoid loading if not used
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api.formatters import TextFormatter, JSONFormatter, SRTFormatter
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="youtube-transcript-api not installed. Run: pip install youtube-transcript-api>=1.0"
        )
    
    # Validate format
    valid_formats = ["text", "json", "srt"]
    if format.lower() not in valid_formats:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid format. Must be one of: {', '.join(valid_formats)}"
        )
    
    # Extract video ID
    video_id = extract_video_id(video)
    if not video_id:
        raise HTTPException(
            status_code=400,
            detail="Could not extract a valid YouTube video ID. Provide a YouTube URL or 11-character video ID."
        )
    
    # Check cache
    cache_key = f"yt-transcript:{video_id}:{format}:{lang}:{translate}:{start}:{end}:{list_langs}"
    cached_result = cache.get(cache_key)
    if cached_result:
        return JSONResponse(content=cached_result)
    
    try:
        # Create API instance
        ytt_api = YouTubeTranscriptApi()
        
        # List available languages
        if list_langs:
            transcript_list = ytt_api.list(video_id)
            langs = []
            for t in transcript_list:
                langs.append({
                    "language_code": t.language_code,
                    "language": t.language,
                    "is_generated": t.is_generated,
                    "is_translatable": t.is_translatable
                })
            
            result = {
                "video_id": video_id,
                "available_transcripts": langs
            }
            cache.set(cache_key, result, expire=3600)  # Cache for 1 hour
            return JSONResponse(content=result)
        
        # Fetch transcript
        transcript = None
        actual_language = None  # Track what language we actually got
        
        if translate:
            # Find source transcript, then translate
            transcript_list = ytt_api.list(video_id)
            if lang:
                try:
                    source = transcript_list.find_transcript([lang])
                    actual_language = source.language_code
                except Exception:
                    available = list(transcript_list)
                    source = available[0] if available else None
                    if not source:
                        raise HTTPException(status_code=404, detail="No transcripts available for this video")
                    actual_language = source.language_code
            else:
                available = list(transcript_list)
                source = available[0] if available else None
                if not source:
                    raise HTTPException(status_code=404, detail="No transcripts available for this video")
                actual_language = source.language_code
            
            transcript = source.translate(translate).fetch()
        else:
            # Auto-detect: if no lang specified, get first available transcript
            if lang:
                transcript = ytt_api.fetch(video_id, languages=[lang])
                actual_language = lang
            else:
                # Get whatever is available - try to list and pick the first one
                try:
                    transcript_list = ytt_api.list(video_id)
                    available = list(transcript_list)
                    if not available:
                        raise HTTPException(status_code=404, detail="No transcripts available for this video")
                    # Prefer manual transcripts over auto-generated
                    manual = [t for t in available if not t.is_generated]
                    source = manual[0] if manual else available[0]
                    actual_language = source.language_code
                    transcript = source.fetch()
                except HTTPException:
                    raise
                except Exception:
                    # Fallback to default fetch (will try common languages)
                    transcript = ytt_api.fetch(video_id)
                    actual_language = "auto"
        
        # Time slicing
        if start is not None or end is not None:
            raw_data = transcript.to_raw_data()
            sliced = []
            for entry in raw_data:
                t = entry.get("start", 0.0)
                if (start is None or t >= start) and (end is None or t <= end):
                    sliced.append(entry)
            transcript = sliced
        
        # Format output
        fmt = format.lower()
        if fmt == "text":
            formatter = TextFormatter()
            formatted_output = formatter.format_transcript(transcript)
        elif fmt == "json":
            formatter = JSONFormatter()
            formatted_output = formatter.format_transcript(transcript, indent=2)
        elif fmt == "srt":
            formatter = SRTFormatter()
            formatted_output = formatter.format_transcript(transcript)
        else:
            formatted_output = str(transcript)
        
        # Calculate stats
        raw_data = transcript.to_raw_data() if hasattr(transcript, 'to_raw_data') else transcript
        total_duration = 0
        word_count = 0
        for entry in raw_data:
            total_duration = max(total_duration, entry.get("start", 0) + entry.get("duration", 0))
            word_count += len(entry.get("text", "").split())
        
        result = {
            "success": True,
            "video_id": video_id,
            "video_url": f"https://www.youtube.com/watch?v={video_id}",
            "format": fmt,
            "language": actual_language or "auto",
            "translated_to": translate,
            "time_range": {
                "start": start,
                "end": end
            } if start or end else None,
            "stats": {
                "segment_count": len(raw_data),
                "word_count": word_count,
                "duration_seconds": round(total_duration, 2)
            },
            "transcript": formatted_output
        }
        
        cache.set(cache_key, result, expire=3600)  # Cache for 1 hour
        return JSONResponse(content=result)
        
    except HTTPException:
        raise
    except Exception as e:
        # youtube-transcript-api failed, try yt-dlp fallback
        try:
            ytdlp_result = await asyncio.get_event_loop().run_in_executor(
                None, 
                lambda: fetch_transcript_ytdlp(video_id, lang)
            )
            
            if list_langs:
                result = {
                    "video_id": video_id,
                    "available_transcripts": [
                        {
                            "language_code": l["code"],
                            "language": l["code"],
                            "is_generated": l["is_generated"],
                            "is_translatable": False
                        } for l in ytdlp_result["available_langs"]
                    ],
                    "source": "yt-dlp"
                }
                cache.set(cache_key, result, expire=3600)
                return JSONResponse(content=result)
            
            transcript = ytdlp_result["transcript"]
            actual_language = ytdlp_result["language"]
            
            # Time slicing
            if start is not None or end is not None:
                sliced = []
                for entry in transcript:
                    t = entry.get("start", 0.0)
                    if (start is None or t >= start) and (end is None or t <= end):
                        sliced.append(entry)
                transcript = sliced
            
            # Format output
            fmt = format.lower()
            if fmt == "text":
                formatted_output = "\n".join(entry["text"] for entry in transcript)
            elif fmt == "json":
                import json
                formatted_output = json.dumps(transcript, indent=2)
            elif fmt == "srt":
                srt_lines = []
                for i, entry in enumerate(transcript, 1):
                    start_time = entry["start"]
                    end_time = start_time + entry.get("duration", 0)
                    def format_srt_time(seconds):
                        h = int(seconds // 3600)
                        m = int((seconds % 3600) // 60)
                        s = int(seconds % 60)
                        ms = int((seconds % 1) * 1000)
                        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
                    srt_lines.append(f"{i}")
                    srt_lines.append(f"{format_srt_time(start_time)} --> {format_srt_time(end_time)}")
                    srt_lines.append(entry["text"])
                    srt_lines.append("")
                formatted_output = "\n".join(srt_lines)
            else:
                formatted_output = str(transcript)
            
            # Calculate stats
            total_duration = 0
            word_count = 0
            for entry in transcript:
                total_duration = max(total_duration, entry.get("start", 0) + entry.get("duration", 0))
                word_count += len(entry.get("text", "").split())
            
            result = {
                "success": True,
                "video_id": video_id,
                "video_url": f"https://www.youtube.com/watch?v={video_id}",
                "format": fmt,
                "language": actual_language,
                "translated_to": None,  # yt-dlp doesn't support translation
                "time_range": {
                    "start": start,
                    "end": end
                } if start or end else None,
                "stats": {
                    "segment_count": len(transcript),
                    "word_count": word_count,
                    "duration_seconds": round(total_duration, 2)
                },
                "transcript": formatted_output,
                "source": "yt-dlp"  # Indicate fallback was used
            }
            
            cache.set(cache_key, result, expire=3600)
            return JSONResponse(content=result)
            
        except Exception as ytdlp_error:
            # Both methods failed
            err_str = str(e).lower()
            if "no transcript" in err_str or "could not retrieve" in err_str or "no subtitles" in str(ytdlp_error).lower():
                raise HTTPException(
                    status_code=404,
                    detail="No transcript found for this video in the requested language."
                )
            if "disabled" in err_str:
                raise HTTPException(
                    status_code=403,
                    detail="Transcripts are disabled for this video."
                )
            if "unavailable" in err_str or "video is unavailable" in err_str:
                raise HTTPException(
                    status_code=404,
                    detail="Video unavailable or does not exist."
                )
            raise HTTPException(
                status_code=500,
                detail=f"Failed to fetch transcript. Primary: {str(e)}. Fallback: {str(ytdlp_error)}"
            )


if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.getenv("PORT", 8001))
    uvicorn.run(app, host="0.0.0.0", port=port)
