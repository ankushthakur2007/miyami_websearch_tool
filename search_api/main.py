from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
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

# Import free stealth and bot detection modules (no API keys needed)
from stealth_client import StealthClient, StealthLevel, stealth_get
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
    
    Args:
        url: URL to fetch
        stealth_mode: "off", "low", "medium", or "high"
        auto_bypass: Automatically try higher stealth levels if blocked
        
    Returns:
        Dict with html, status_code, final_url, fetch_method, protection_info
    """
    fetch_method = "standard"
    protection_info = None
    
    # Step 1: Fetch using stealth mode or standard
    if stealth_mode != "off":
        # Use stealth client (FREE - no API keys needed)
        try:
            level = StealthLevel(stealth_mode.lower())
            client = get_stealth_client()
            response = await client.get(url, stealth_level=level)
            html = response.text
            status_code = response.status_code
            final_url = response.url
            fetch_method = f"stealth_{stealth_mode}"
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Stealth fetch failed: {str(e)}")
    else:
        # Standard fetch
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "DNT": "1",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1"
            }
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            html = response.text
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
                    new_html = response.text
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
                    new_html = response.text
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

@app.get("/")
async def root():
    return {
        "message": "SearXNG Search API",
        "endpoints": {
            "/search-api": "Search using SearXNG engines",
            "/fetch": "Fetch and clean website content",
            "/search-and-fetch": "Search and auto-fetch content from top N results",
            "/deep-research": "Recursive research agent for comprehensive analysis",
            "/crawl-site": "Crawl entire websites and extract content from multiple pages"
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
        if stealth_mode != "off":
            middleware_path = os.path.join(os.path.dirname(__file__), 'stealth_middleware.py')
            cmd.extend([
                '-s', 'DOWNLOADER_MIDDLEWARES_BASE={\'scrapy.downloadermiddlewares.httpauth.HttpAuthMiddleware\': 300}',
                '-s', 'DOWNLOADER_MIDDLEWARES={\'stealth_middleware.StealthDownloaderMiddleware\': 585}',
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

if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.getenv("PORT", 8001))
    uvicorn.run(app, host="0.0.0.0", port=port)
