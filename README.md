# SearXNG Search API for LLMs

A FastAPI wrapper for SearXNG that provides LLM-friendly search and web content extraction capabilities.

**🔗 Live API:** `https://websearch.miyami.tech`

## 🚀 Features

- **🔍 Web Search API**: Search using multiple search engines via SearXNG
- **⏰ Time-Range Filters**: Filter search results by recency (day, week, month, year)
- **📄 Enhanced Content Extraction**: Fetch and clean webpage content with **Trafilatura** (Firecrawl-quality)
- **📝 Markdown Output**: Get structured markdown like Firecrawl
- **🎯 Search & Fetch**: Automatically search and fetch full content from top N results
- **🧠 Semantic Reranking**: AI-powered reranking for better search relevance (FlashRank)
- **💾 Smart Caching**: Built-in caching for faster repeated queries (DiskCache)
- **🔬 Deep Research**: Multi-query parallel research with compiled markdown reports
- **🛡️ Stealth Mode**: FREE anti-bot bypass (no API keys needed)
- **⚡ Fast & Async**: Built with FastAPI and async/await
- **🤖 LLM Optimized**: Clean JSON/Markdown responses perfect for LLM consumption

## 🛠️ API Endpoints

### 1. `/search-api` - Web Search

Search the web using multiple engines and get structured results.

**Parameters:**
- `query` (required) - Search query
- `categories` (optional) - Search categories (default: general)
- `language` (optional) - Language code (default: en)
- `time_range` (optional) - Filter by recency: `day`, `week`, `month`, `year`
- `rerank` (optional) - Set to `true` to enable AI semantic reranking

**Examples:**
```bash
# Basic search
curl "https://websearch.miyami.tech/search-api?query=weather&categories=general"

# Recent news (past 24 hours)
curl "https://websearch.miyami.tech/search-api?query=AI+news&time_range=day"

# With AI reranking
curl "https://websearch.miyami.tech/search-api?query=python+tutorials&rerank=true"
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
      "engine": "brave",
      "score": 1.5
    }
  ],
  "suggestions": ["weather forecast"],
  "infoboxes": []
}
```

---

### 2. `/fetch` - Content Extraction

Extract clean, readable content from any webpage with **Firecrawl-like quality**.

**Features:**
- 🎯 **Trafilatura extraction** - Better accuracy than basic parsers
- 📝 **Markdown output** - Get structured markdown
- 📊 **Rich metadata** - Authors, dates, site names automatically extracted
- 🛡️ **Stealth Mode** (FREE) - Anti-bot bypass with User-Agent rotation
- 🔓 **Auto-Bypass** (FREE) - Automatically escalate stealth levels if blocked

**Parameters:**
- `url` (required) - URL to fetch
- `format` - Output format: `text`, `markdown`, or `html` (default: text)
- `extraction_mode` - Engine: `trafilatura` (best) or `readability` (faster)
- `include_links` - Include extracted links (default: true)
- `include_images` - Include images (default: true)
- `max_content_length` - Max content length (default: 100000)
- `stealth_mode` - Anti-bot bypass: `off`, `low`, `medium`, `high`
- `auto_bypass` - Auto-escalate stealth levels if blocked

**Examples:**
```bash
# Basic fetch with markdown output
curl "https://websearch.miyami.tech/fetch?url=https://example.com&format=markdown"

# With stealth mode for protected sites
curl "https://websearch.miyami.tech/fetch?url=https://protected-site.com&stealth_mode=high&auto_bypass=true"
```

**Response:**
```json
{
  "success": true,
  "url": "https://example.com",
  "status_code": 200,
  "fetch_method": "stealth_medium",
  "metadata": {
    "title": "Example Article",
    "author": "John Doe",
    "date": "2024-01-15",
    "sitename": "Example Site"
  },
  "content": "# Example Article\n\nClean markdown content...",
  "stats": {
    "content_length": 5420,
    "word_count": 890,
    "extraction_mode": "trafilatura",
    "format": "markdown"
  }
}
```

---

### 3. `/search-and-fetch` - Search & Auto-Fetch Content

**The most powerful endpoint!** Searches and automatically fetches full content from top N results.

**Parameters:**
- `query` (required) - Search query
- `num_results` (optional) - Number of results to fetch (1-5, default: 3)
- `format` (optional) - Output format: text, markdown, html (default: markdown)
- `categories` (optional) - Search categories (default: general)
- `time_range` (optional) - Filter by recency: `day`, `week`, `month`, `year`
- `rerank` (optional) - Enable AI semantic reranking
- `stealth_mode` (optional) - Anti-bot bypass: `off`, `low`, `medium`, `high`
- `auto_bypass` (optional) - Auto-escalate stealth levels if blocked

**Examples:**
```bash
# Search and fetch top 3 results
curl "https://websearch.miyami.tech/search-and-fetch?query=python+tutorials&num_results=3&format=markdown"

# Recent AI news with full content
curl "https://websearch.miyami.tech/search-and-fetch?query=AI+news&time_range=day&num_results=5"

# With stealth mode
curl "https://websearch.miyami.tech/search-and-fetch?query=web+scraping&stealth_mode=high&auto_bypass=true"
```

**Response:**
```json
{
  "query": "python tutorials",
  "num_results_requested": 3,
  "num_results_found": 3,
  "successful_fetches": 2,
  "failed_fetches": 1,
  "fetch_options": {
    "stealth_mode": "off",
    "auto_bypass": false
  },
  "results": [
    {
      "search_result": {
        "title": "Python Tutorial",
        "url": "https://example.com",
        "snippet": "Learn Python..."
      },
      "fetch_status": "success",
      "fetched_content": {
        "title": "Python Tutorial",
        "content": "Full article content...",
        "word_count": 890
      }
    }
  ]
}
```

---

### 4. `/deep-research` - Multi-Query Research

Perform comprehensive research across multiple queries in parallel.

**Parameters:**
- `queries` (required) - Comma-separated list of queries (max 10)
- `breadth` (optional) - Results per query (1-5, default: 3)
- `time_range` (optional) - Filter by recency
- `max_content_length` (optional) - Max content per result (default: 30000)
- `stealth_mode` (optional) - Anti-bot bypass
- `auto_bypass` (optional) - Auto-escalate stealth levels

**Examples:**
```bash
# Research multiple topics
curl "https://websearch.miyami.tech/deep-research?queries=AI+trends,machine+learning,GPT&breadth=2"

# With time filter
curl "https://websearch.miyami.tech/deep-research?queries=python+news,javascript+updates&time_range=month"
```

**Response:**
```json
{
  "research_summary": {
    "total_queries": 3,
    "successful_queries": 3,
    "total_results_found": 6,
    "total_successful_fetches": 6
  },
  "queries": ["AI trends", "machine learning", "GPT"],
  "query_results": [...],
  "compiled_report": "# Deep Research Report\n\n..."
}
```

---

### 5. `/health` - Health Check

```bash
curl "https://websearch.miyami.tech/health"
```

### 6. `/docs` - Interactive API Documentation

Visit `https://websearch.miyami.tech/docs` for Swagger UI

---

## 🛡️ Stealth Mode (FREE)

The stealth mode helps bypass bot detection without any API keys:

| Level | Description |
|-------|-------------|
| `off` | Standard fetch |
| `low` | Basic User-Agent rotation |
| `medium` | UA + header randomization |
| `high` | UA + headers + TLS fingerprint (requires `curl_cffi`) |

**Auto-bypass:** Set `auto_bypass=true` to automatically escalate stealth levels if blocked.

**Detected protections:** Cloudflare, reCAPTCHA, hCaptcha, DataDome, Akamai, PerimeterX, Imperva

---

## 💻 Local Development

### Run with Docker
```bash
docker build -t searxng-api .
docker run -p 8080:8080 searxng-api
```

Access at: `http://localhost:8080`

### Run without Docker

1. **Start SearXNG**:
```bash
cd searxng
export PYTHONPATH="$PWD:$PYTHONPATH"
python3 -m searx.webapp
```

2. **Start FastAPI** (in another terminal):
```bash
cd search_api
pip install -r requirements.txt
uvicorn main:app --reload --port 8001
```

Access FastAPI at: `http://localhost:8001`

---

## 🤖 Usage with AI Agents

### Python Example

```python
import httpx

BASE_URL = "https://websearch.miyami.tech"

async def search(query: str, time_range: str = None):
    """Search the web"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        params = {"query": query}
        if time_range:
            params["time_range"] = time_range
        response = await client.get(f"{BASE_URL}/search-api", params=params)
        return response.json()

async def fetch(url: str, stealth_mode: str = "off"):
    """Fetch webpage content"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{BASE_URL}/fetch",
            params={"url": url, "format": "markdown", "stealth_mode": stealth_mode}
        )
        return response.json()

async def search_and_fetch(query: str, num_results: int = 3):
    """Search and fetch full content"""
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(
            f"{BASE_URL}/search-and-fetch",
            params={"query": query, "num_results": num_results, "format": "markdown"}
        )
        return response.json()
```

### MCP Tool Definitions

```json
[
  {
    "name": "web_search",
    "description": "Search the web using multiple search engines",
    "inputSchema": {
      "type": "object",
      "properties": {
        "query": {"type": "string", "description": "Search query"},
        "time_range": {"type": "string", "enum": ["day", "week", "month", "year"]}
      },
      "required": ["query"]
    }
  },
  {
    "name": "fetch_webpage",
    "description": "Fetch and extract clean content from a webpage",
    "inputSchema": {
      "type": "object",
      "properties": {
        "url": {"type": "string", "description": "URL to fetch"},
        "stealth_mode": {"type": "string", "enum": ["off", "low", "medium", "high"]}
      },
      "required": ["url"]
    }
  },
  {
    "name": "search_and_fetch",
    "description": "Search and fetch full content from top results",
    "inputSchema": {
      "type": "object",
      "properties": {
        "query": {"type": "string", "description": "Search query"},
        "num_results": {"type": "integer", "description": "Number of results (1-5)"}
      },
      "required": ["query"]
    }
  }
]
```

---

## 📊 Architecture

```
┌─────────────┐
│   Client    │
│   (LLM)     │
└──────┬──────┘
       │ HTTPS
       ↓
┌─────────────────────────┐
│   FastAPI (Port 8080)   │
│  - /search-api          │
│  - /fetch               │
│  - /search-and-fetch    │
│  - /deep-research       │
└──────┬──────────────────┘
       │ HTTP (internal)
       ↓
┌─────────────────────────┐
│  SearXNG (Port 8888)    │
│  - DuckDuckGo, Google   │
│  - Bing, Brave, etc.    │
└─────────────────────────┘
```

---

## 📝 License

- SearXNG: AGPL-3.0 License
- FastAPI: MIT License

---

Built with ❤️ for the LLM community
