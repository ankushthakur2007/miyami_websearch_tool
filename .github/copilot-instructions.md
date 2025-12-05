# Copilot Instructions for miyami_websearch_tool

## Architecture Overview

This is a **FastAPI wrapper around SearXNG** that provides LLM-optimized search and content extraction APIs. The system runs two services in a single Docker container:

1. **SearXNG** (port 8888, internal): Meta-search engine aggregating results from DuckDuckGo, Google, Bing, Brave, Wikipedia, Startpage
2. **FastAPI** (port 8080, exposed): The API layer in `search_api/main.py` that wraps SearXNG and adds content extraction

**Key data flow**: User → FastAPI → SearXNG → Multiple search engines → FastAPI (processing/caching) → User

## Project Structure

```
search_api/
  main.py               # All API logic - endpoints, extraction, caching
  stealth_client.py     # Anti-bot HTTP client with UA rotation, TLS fingerprinting (FREE)
  antibot.py            # Bot detection for Cloudflare, reCAPTCHA, DataDome, etc. (FREE)
  requirements.txt      # Python dependencies
Dockerfile              # Multi-service container (SearXNG + FastAPI)
start.sh                # Orchestrates both services with health checks
searxng_settings.yml    # Search engine configuration and enabled engines
render.yaml             # Render.com deployment config
```

## Core API Endpoints (in `main.py`)

| Endpoint | Purpose |
|----------|---------|
| `/search-api` | Search via SearXNG with optional time filtering and AI reranking |
| `/fetch` | Extract clean content from URLs with FREE stealth mode |
| `/search-and-fetch` | Combined: search + parallel content extraction with stealth support |
| `/deep-research` | Multi-query research: processes queries in parallel with stealth mode |
| `/health` | Health check verifying SearXNG connectivity |

## Key Patterns & Technologies

### Caching
- Uses **DiskCache** at `/tmp/miyami_cache` with 1-hour expiration
- Cache keys combine query params including stealth options
- Always check cache before external calls

### Content Extraction (in `/fetch` and `/search-and-fetch`)
- **Trafilatura** (default): Best quality, extracts metadata (author, date, sitename)
- **Readability** (fallback): Faster but less metadata
- Output formats: `text`, `markdown`, `html`

### Stealth Mode & Anti-Bot Bypass (FREE - No API Keys Needed)
- **StealthClient** (`stealth_client.py`): HTTP client with anti-detection capabilities
  - `low`: Basic User-Agent rotation
  - `medium`: UA + header randomization
  - `high`: UA + headers + TLS fingerprint matching (via `curl_cffi`)
- **antibot.py**: Detects bot protection (Cloudflare, reCAPTCHA, hCaptcha, DataDome, Akamai, PerimeterX, Imperva, Kasada)
- **auto_bypass**: Automatically escalates stealth levels if blocked

### AI Reranking
- Uses **FlashRank** with `ms-marco-TinyBERT-L-2-v2` model (lazy-loaded)
- Enabled via `?rerank=true` query param
- Wraps results in `RerankRequest` with `{id, text, meta}` structure

### Async Patterns
- All HTTP calls use `httpx.AsyncClient` with 30s timeout
- Parallel fetching in `/search-and-fetch` via `asyncio.gather()`
- SearXNG accessed at `http://127.0.0.1:8888`
- `advanced_fetch()` helper function handles stealth logic

## Development & Deployment

### Local Development
```bash
# Run FastAPI standalone (without SearXNG)
cd search_api && uvicorn main:app --reload --port 8001

# Full stack with Docker
docker build -t miyami-search . && docker run -p 8080:8080 miyami-search
```

### Environment Variables
- `PORT`: FastAPI port (default: 8080, Render uses 10000)
- `SEARXNG_SECRET`: Required for production (generate with `openssl rand -hex 32`)
- `SEARXNG_BIND_ADDRESS`: Internal SearXNG address (default: 127.0.0.1)
- `SEARXNG_PORT`: Internal SearXNG port (default: 8888)

### Deployment
- **Render.com**: Primary deployment via `render.yaml` (Docker, free tier)
- **Railway**: Alternative via `DEPLOYMENT.md`
- Health checks hit `/health` which verifies SearXNG connectivity

## Code Conventions

- HTTP errors use `HTTPException` with specific status codes (400, 503, 500)
- All endpoints return `JSONResponse` with structured data
- Time range validation: `["day", "week", "month", "year"]`
- Stealth mode validation: `["off", "low", "medium", "high"]`
- Content truncation uses `max_content_length` param with `"... [truncated]"` marker
- `advanced_fetch()` is the central function for all fetch operations

## Adding New Endpoints

Follow this pattern from existing endpoints:
1. Add cache key combining relevant params (including stealth options)
2. Check cache first, return if hit
3. Use `advanced_fetch()` for URL fetching with stealth support
4. Make async HTTP calls with proper error handling
5. Cache successful results before returning
6. Wrap errors in `HTTPException` with appropriate status codes

## Stealth Mode Usage (FREE)

```python
# In endpoint, use advanced_fetch:
fetch_result = await advanced_fetch(
    url=url,
    stealth_mode="high",      # off, low, medium, high
    auto_bypass=True          # Auto-escalate stealth levels if blocked
)
html = fetch_result["html"]
protection_info = fetch_result["protection_info"]  # Bot detection results
```
