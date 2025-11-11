from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
import httpx
from bs4 import BeautifulSoup
from readability import Document
from typing import Optional, List, Dict, Any
import asyncio
from urllib.parse import urljoin, urlparse

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
    page: Optional[int] = Query(1, description="Page number")
):
    """
    Search using SearXNG and return JSON results
    
    Example: /search-api?query=weather&categories=general
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
    include_html: bool = Query(False, description="Include raw HTML"),
    include_links: bool = Query(True, description="Include extracted links"),
    max_content_length: int = Query(50000, description="Maximum content length")
):
    """
    Fetch a URL and return cleaned, structured content
    
    Example: /fetch?url=https://example.com
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
                "User-Agent": "Mozilla/5.0 (compatible; SearXNG-API-Bot/1.0)"
            }
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            
            html_content = response.text
            
            # Use readability to extract main content
            doc = Document(html_content)
            
            # Parse with BeautifulSoup for additional extraction
            soup = BeautifulSoup(html_content, 'lxml')
            
            # Extract metadata
            metadata = {
                "title": doc.title(),
                "url": str(response.url),
                "status_code": response.status_code,
                "content_type": response.headers.get("content-type", ""),
            }
            
            # Extract meta tags
            meta_description = soup.find("meta", attrs={"name": "description"})
            if meta_description:
                metadata["description"] = meta_description.get("content", "")
            
            # Extract main content using readability
            article_html = doc.summary()
            article_soup = BeautifulSoup(article_html, 'lxml')
            
            # Get clean text
            main_text = article_soup.get_text(separator="\n", strip=True)
            
            # Limit content length
            if len(main_text) > max_content_length:
                main_text = main_text[:max_content_length] + "..."
            
            result = {
                "metadata": metadata,
                "content": main_text,
                "short_title": doc.short_title(),
            }
            
            # Extract links if requested
            if include_links:
                links = []
                for link in article_soup.find_all('a', href=True):
                    href = link['href']
                    absolute_url = urljoin(url, href)
                    links.append({
                        "text": link.get_text(strip=True),
                        "url": absolute_url
                    })
                result["links"] = links[:50]  # Limit to 50 links
            
            # Include raw HTML if requested
            if include_html:
                result["html"] = article_html
            
            # Extract headings
            headings = []
            for heading in article_soup.find_all(['h1', 'h2', 'h3']):
                headings.append({
                    "level": heading.name,
                    "text": heading.get_text(strip=True)
                })
            result["headings"] = headings
            
            # Extract images
            images = []
            for img in article_soup.find_all('img', src=True):
                img_url = urljoin(url, img['src'])
                images.append({
                    "url": img_url,
                    "alt": img.get('alt', ''),
                })
            result["images"] = images[:20]  # Limit to 20 images
            
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
    max_content_length: int = Query(50000, description="Maximum content length per page")
):
    """
    Search and automatically fetch full content from top N results
    
    This is a convenience endpoint that:
    1. Searches for your query
    2. Gets top N results (default: 3, max: 5)
    3. Fetches full webpage content for each result
    4. Returns both search snippets AND full content
    
    Example: /search-and-fetch?query=python+tutorials&num_results=3
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
            """Fetch content for a single search result"""
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
                    headers={"User-Agent": "Mozilla/5.0 (compatible; SearXNG-API-Bot/1.0)"}
                ) as client:
                    response = await client.get(url)
                    response.raise_for_status()
                    
                    html_content = response.text
                    doc = Document(html_content)
                    article_html = doc.summary()
                    article_soup = BeautifulSoup(article_html, 'lxml')
                    main_text = article_soup.get_text(separator="\n", strip=True)
                    
                    # Limit content length
                    if len(main_text) > max_content_length:
                        main_text = main_text[:max_content_length] + "... (truncated)"
                    
                    # Extract headings
                    headings = []
                    for heading in article_soup.find_all(['h1', 'h2', 'h3']):
                        headings.append({
                            "level": heading.name,
                            "text": heading.get_text(strip=True)
                        })
                    
                    return {
                        "search_result": {
                            "title": result.get("title", ""),
                            "url": url,
                            "snippet": result.get("content", ""),
                            "engine": result.get("engine", ""),
                            "score": result.get("score", 0)
                        },
                        "fetch_status": "success",
                        "fetched_content": {
                            "title": doc.title(),
                            "content": main_text,
                            "headings": headings[:10],  # Limit to 10 headings
                            "content_length": len(main_text)
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
