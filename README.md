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
- **🕷️ Site Crawler**: Recursive website crawling with Scrapy integration
- **🎬 YouTube Transcripts**: Fetch video transcripts with language selection and translation
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

### 5. `/crawl-site` - Website Crawler

Recursively crawl an entire website and extract content from multiple pages using Scrapy.

**Features:**
- 🕷️ **Scrapy-powered** - Industrial-strength web crawling
- 🎯 **Depth control** - Limit crawl depth (0-5 levels)
- 📊 **Page limits** - Control max pages (1-200)
- 🔍 **URL filtering** - Include/exclude patterns with regex
- 🛡️ **Stealth mode** - Anti-bot bypass for protected sites
- 🤖 **Robots.txt** - Respect or bypass robots.txt rules
- 📝 **Content extraction** - Uses Trafilatura for clean content

**Parameters:**
- `start_url` (required) - Starting URL to crawl
- `max_pages` (optional) - Maximum pages to crawl (1-200, default: 50)
- `max_depth` (optional) - Maximum crawl depth (0-5, default: 2)
- `format` (optional) - Output format: `text`, `markdown`, `html` (default: markdown)
- `include_links` (optional) - Include extracted links (default: true)
- `include_images` (optional) - Include images (default: true)
- `url_patterns` (optional) - Comma-separated regex patterns to include (e.g., `/blog/,/docs/`)
- `exclude_patterns` (optional) - Comma-separated regex patterns to exclude
- `stealth_mode` (optional) - Anti-bot bypass: `off`, `low`, `medium`, `high`
- `obey_robots` (optional) - Respect robots.txt (default: true)

**Examples:**
```bash
# Basic site crawl
curl "https://websearch.miyami.tech/crawl-site?start_url=https://example.com&max_pages=10"

# Crawl with depth limit and URL filtering
curl "https://websearch.miyami.tech/crawl-site?start_url=https://docs.example.com&max_depth=3&url_patterns=/api/,/guides/"

# Bypass robots.txt for protected sites
curl "https://websearch.miyami.tech/crawl-site?start_url=https://site.com&max_pages=5&obey_robots=false"

# Crawl specific sections only
curl "https://websearch.miyami.tech/crawl-site?start_url=https://blog.example.com&url_patterns=/2024/,/tech/&exclude_patterns=/archive/"
```

**Response:**
```json
{
  "crawl_summary": {
    "start_url": "https://example.com",
    "pages_crawled": 10,
    "max_pages_requested": 10,
    "max_depth": 2,
    "format": "markdown",
    "stealth_mode": "off"
  },
  "pages": [
    {
      "url": "https://example.com/page1",
      "status_code": 200,
      "depth": 0,
      "metadata": {
        "title": "Page Title",
        "author": "John Doe",
        "date": "2024-01-15",
        "sitename": "Example Site"
      },
      "content": "# Page Title\n\nClean markdown content...",
      "word_count": 890,
      "format": "markdown",
      "links": ["https://example.com/page2"],
      "images": ["https://example.com/image.jpg"]
    }
  ],
  "total_words": 8900
}
```

**Use Cases:**
- 📚 Documentation crawling
- 📰 Blog archiving
- 🔍 Site auditing
- 📊 Content analysis
- 🗃️ Knowledge base extraction

**Limitations:**
- JavaScript-heavy sites (React/Vue SPAs) may have limited content
- Use `/fetch` endpoint for better single-page extraction on JS sites
- For protected sites, combine `obey_robots=false` with stealth mode

---

### 6. `/yt-transcript` - YouTube Transcripts

Fetch YouTube video transcripts for LLM consumption.

**Features:**
- 🎬 **YouTube URL or Video ID** - Accepts any YouTube link format
- 📝 **Multiple formats** - Text, JSON (with timestamps), or SRT subtitles
- 🌍 **Language selection** - Choose preferred transcript language
- 🔄 **Translation** - Translate transcripts to any supported language
- ⏱️ **Time slicing** - Extract specific portions by timestamp
- 📊 **Stats included** - Word count, segment count, duration

**Parameters:**
- `video` (required) - YouTube video URL or 11-character video ID
- `format` (optional) - Output format: `text`, `json`, `srt` (default: text)
- `lang` (optional) - Preferred language code (e.g., 'en', 'es', 'hi')
- `translate` (optional) - Translate to target language code
- `start` (optional) - Start time in seconds for trimming
- `end` (optional) - End time in seconds for trimming
- `list_langs` (optional) - Set to `true` to list available languages

**Examples:**
```bash
# Basic transcript (text format)
curl "https://websearch.miyami.tech/yt-transcript?video=dQw4w9WgXcQ&format=text"

# With full YouTube URL
curl "https://websearch.miyami.tech/yt-transcript?video=https://youtube.com/watch?v=dQw4w9WgXcQ"

# JSON format with timestamps
curl "https://websearch.miyami.tech/yt-transcript?video=dQw4w9WgXcQ&format=json"

# SRT subtitle format
curl "https://websearch.miyami.tech/yt-transcript?video=dQw4w9WgXcQ&format=srt"

# Specific language
curl "https://websearch.miyami.tech/yt-transcript?video=dQw4w9WgXcQ&lang=en"

# Translate to Spanish
curl "https://websearch.miyami.tech/yt-transcript?video=dQw4w9WgXcQ&translate=es"

# Time range (60-120 seconds)
curl "https://websearch.miyami.tech/yt-transcript?video=dQw4w9WgXcQ&start=60&end=120"

# List available languages
curl "https://websearch.miyami.tech/yt-transcript?video=dQw4w9WgXcQ&list_langs=true"
```

**Response:**
```json
{
  "success": true,
  "video_id": "dQw4w9WgXcQ",
  "video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "format": "text",
  "language": "auto",
  "translated_to": null,
  "time_range": null,
  "stats": {
    "segment_count": 61,
    "word_count": 487,
    "duration_seconds": 211.32
  },
  "transcript": "[♪♪♪]\n♪ We're no strangers to love ♪\n♪ You know the rules and so do I ♪..."
}
```

**Use Cases:**
- 📚 Video content summarization
- 🔍 Searching within video content
- 📖 Creating study notes from lectures
- 🌐 Translating video content
- ♿ Accessibility improvements

---

### 7. `/health` - Health Check

```bash
curl "https://websearch.miyami.tech/health"
```

### 8. `/docs` - Interactive API Documentation

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

**Note:** The `/crawl-site` endpoint requires Scrapy dependencies. Make sure you've installed all requirements:
```bash
pip install scrapy>=2.11.0 itemadapter>=0.8.0
```

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

async def crawl_site(start_url: str, max_pages: int = 10, max_depth: int = 2):
    """Crawl an entire website"""
    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.get(
            f"{BASE_URL}/crawl-site",
            params={
                "start_url": start_url,
                "max_pages": max_pages,
                "max_depth": max_depth,
                "format": "markdown"
            }
        )
        return response.json()

async def get_youtube_transcript(video: str, format: str = "text", translate: str = None):
    """Get YouTube video transcript"""
    async with httpx.AsyncClient(timeout=60.0) as client:
        params = {"video": video, "format": format}
        if translate:
            params["translate"] = translate
        response = await client.get(f"{BASE_URL}/yt-transcript", params=params)
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
  },
  {
    "name": "crawl_site",
    "description": "Recursively crawl an entire website and extract content from multiple pages",
    "inputSchema": {
      "type": "object",
      "properties": {
        "start_url": {"type": "string", "description": "Starting URL to crawl"},
        "max_pages": {"type": "integer", "description": "Maximum pages to crawl (1-200)"},
        "max_depth": {"type": "integer", "description": "Maximum crawl depth (0-5)"},
        "url_patterns": {"type": "string", "description": "Comma-separated regex patterns to include"},
        "obey_robots": {"type": "boolean", "description": "Respect robots.txt rules"}
      },
      "required": ["start_url"]
    }
  },
  {
    "name": "youtube_transcript",
    "description": "Fetch YouTube video transcripts for summarization and analysis",
    "inputSchema": {
      "type": "object",
      "properties": {
        "video": {"type": "string", "description": "YouTube video URL or 11-character video ID"},
        "format": {"type": "string", "enum": ["text", "json", "srt"], "description": "Output format"},
        "lang": {"type": "string", "description": "Preferred language code"},
        "translate": {"type": "string", "description": "Translate to target language code"}
      },
      "required": ["video"]
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
