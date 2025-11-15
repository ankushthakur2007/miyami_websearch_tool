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
            "/search-and-fetch": "Search and auto-fetch content from top N results"
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
    time_range: Optional[str] = Query(None, description="Time filter: day (past 24h), week (past week), month (past month), year (past year)")
):
    """
    Search using SearXNG and return JSON results with optional time filtering
    
    Time Range Options:
    - day: Results from the past 24 hours
    - week: Results from the past week
    - month: Results from the past month
    - year: Results from the past year
    - None: All results (default)
    
    Example: /search-api?query=AI+news&categories=general&time_range=day
    """
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
    extraction_mode: str = Query("trafilatura", description="Extraction engine: trafilatura (best) or readability (fast)")
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
    
    Example: /fetch?url=https://example.com&format=markdown
    """
    try:
        # Validate URL
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            raise HTTPException(status_code=400, detail="Invalid URL format")
        
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
            
            html_content = response.text
            final_url = str(response.url)
            
            # Initialize result structure
            result = {
                "success": True,
                "url": final_url,
                "status_code": response.status_code,
            }
            
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
                    import json
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
                        "content_type": response.headers.get("content-type", "")
                    }
                    
                    # Clean empty values
                    metadata = {k: v for k, v in metadata.items() if v}
                    result["metadata"] = metadata
                    
                    # Get main text
                    main_text = data.get("text", "")
                    
                    # Format output based on requested format
                    if format == "markdown":
                        # Convert to markdown
                        h = html2text.HTML2Text()
                        h.ignore_links = not include_links
                        h.ignore_images = not include_images
                        h.body_width = 0  # No wrapping
                        
                        # Get raw text or try to extract markdown
                        raw_html = data.get("raw_text", main_text)
                        if data.get("fingerprint"):
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
                        else:
                            result["content"] = main_text
                            
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
                    "status_code": response.status_code,
                    "content_type": response.headers.get("content-type", ""),
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
                "format": format
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
    time_range: Optional[str] = Query(None, description="Time filter: day, week, month, year")
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
    
    Example: /search-and-fetch?query=AI+news&num_results=3&format=markdown&time_range=day
    """
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
        top_results = search_data.get("results", [])[:num_results]
        
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
                async with httpx.AsyncClient(
                    timeout=30.0,
                    follow_redirects=True,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    }
                ) as client:
                    response = await client.get(url)
                    response.raise_for_status()
                    
                    html_content = response.text
                    final_url = str(response.url)
                    
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
                        import json
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
                        
                        return {
                            "search_result": {
                                "title": result.get("title", ""),
                                "url": final_url,
                                "snippet": result.get("content", ""),
                                "engine": result.get("engine", ""),
                                "score": result.get("score", 0)
                            },
                            "fetch_status": "success",
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
                        
                        return {
                            "search_result": {
                                "title": result.get("title", ""),
                                "url": final_url,
                                "snippet": result.get("content", ""),
                                "engine": result.get("engine", ""),
                                "score": result.get("score", 0)
                            },
                            "fetch_status": "success",
                            "fetched_content": {
                                "title": doc.title(),
                                "content": content,
                                "word_count": len(content.split()),
                                "format": format
                            }
                        }
                    
            except httpx.HTTPStatusError as e:
                return {
                    "search_result": result,
                    "fetch_status": "error",
                    "fetch_error": f"HTTP {e.response.status_code}: {str(e)}",
                    "content": None
                }
            except httpx.RequestError as e:
                return {
                    "search_result": result,
                    "fetch_status": "error",
                    "fetch_error": f"Connection error: {str(e)}",
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
        
        return JSONResponse(content={
            "query": query,
            "num_results_requested": num_results,
            "num_results_found": len(top_results),
            "successful_fetches": successful_fetches,
            "failed_fetches": failed_fetches,
            "results": fetched_results,
            "suggestions": search_data.get("suggestions", [])
        })
        
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"Search failed: {str(e)}")
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"Cannot connect to SearXNG: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")

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
