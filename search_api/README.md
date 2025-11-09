# SearXNG Search API

FastAPI wrapper for SearXNG providing LLM-friendly search and web fetching capabilities.

## Features

- **Search API**: Query SearXNG engines and get clean JSON results
- **Fetch API**: Extract and clean content from any webpage
- Async/await support for fast performance
- Structured JSON responses optimized for LLM consumption

## Setup

1. Make sure SearXNG is running on `http://127.0.0.1:8888`
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Running

Start the API server:
```bash
python main.py
```

Or with uvicorn:
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

The API will be available at `http://localhost:8000`

## API Endpoints

### 1. Search API - `/search-api`

Search using SearXNG engines and get structured results.

**Parameters:**
- `query` (required): Search query
- `categories` (optional): Search categories (general, images, videos, news, etc.)
- `engines` (optional): Specific engines to use
- `language` (optional): Search language (default: en)
- `page` (optional): Page number (default: 1)

**Example:**
```bash
curl "http://localhost:8000/search-api?query=weather&categories=general"
```

**Response:**
```json
{
  "query": "weather",
  "number_of_results": 150,
  "results": [
    {
      "title": "Weather.com",
      "url": "https://weather.com",
      "content": "Get the latest weather...",
      "engine": "google",
      "score": 1.5
    }
  ],
  "suggestions": ["weather forecast", "weather radar"],
  "infoboxes": []
}
```

### 2. Fetch API - `/fetch`

Fetch and clean webpage content, extracting main text, links, headings, and images.

**Parameters:**
- `url` (required): URL to fetch
- `include_html` (optional): Include raw HTML (default: false)
- `include_links` (optional): Include extracted links (default: true)
- `max_content_length` (optional): Maximum content length (default: 50000)

**Example:**
```bash
curl "http://localhost:8000/fetch?url=https://example.com"
```

**Response:**
```json
{
  "metadata": {
    "title": "Example Domain",
    "url": "https://example.com",
    "status_code": 200,
    "description": "Example website"
  },
  "content": "Clean extracted text content...",
  "short_title": "Example",
  "links": [
    {"text": "More information", "url": "https://example.com/more"}
  ],
  "headings": [
    {"level": "h1", "text": "Example Domain"}
  ],
  "images": [
    {"url": "https://example.com/image.png", "alt": "Example"}
  ]
}
```

### 3. Health Check - `/health`

Check if the API and SearXNG are running.

**Example:**
```bash
curl "http://localhost:8000/health"
```

## Documentation

Interactive API documentation available at:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Usage with LLMs

This API is designed to be easily integrated with LLMs:

1. **For web search**: Use `/search-api` to search the web and get relevant results
2. **For content extraction**: Use `/fetch` to extract clean content from specific URLs
3. Both endpoints return clean, structured JSON optimized for LLM processing

## Example LLM Integration

```python
import httpx

async def search_web(query: str):
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "http://localhost:8000/search-api",
            params={"query": query, "categories": "general"}
        )
        return response.json()

async def fetch_webpage(url: str):
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "http://localhost:8000/fetch",
            params={"url": url}
        )
        return response.json()
```

## Notes

- SearXNG must be running before starting this API
- Default SearXNG URL: `http://127.0.0.1:8888`
- API runs on port 8000 by default
- All responses are in JSON format
