# SearXNG Search API for LLMs

A production-ready FastAPI wrapper for SearXNG that provides LLM-friendly search and web content extraction capabilities.

## 🚀 Features

- **🔍 Web Search API**: Search using multiple search engines via SearXNG
- **📄 Enhanced Content Extraction**: Fetch and clean webpage content with **Trafilatura** (Firecrawl-quality)
- **📝 Markdown Output**: Get structured markdown like Firecrawl (NEW!)
- **🎯 Search & Fetch**: Automatically search and fetch full content from top N results
- **⚡ Fast & Async**: Built with FastAPI and async/await
- **🐳 Docker Ready**: One-command deployment
- **☁️ Cloud Deploy**: Pre-configured for Render
- **🆓 Free Hosting**: Runs on Render free tier (750 hours/month)
- **🤖 LLM Optimized**: Clean JSON/Markdown responses perfect for LLM consumption

## 📁 Project Structure

```
miyami_search_api/
├── search_api/          # FastAPI application
│   ├── main.py         # API endpoints
│   ├── requirements.txt
│   └── README.md
├── searxng/            # SearXNG (cloned during Docker build)
├── Dockerfile          # Multi-service Docker container
├── fly.toml           # Fly.io configuration
├── start.sh           # Startup script for both services
├── searxng_settings.yml # SearXNG configuration
└── DEPLOYMENT.md      # Deployment guide
```

## 🛠️ API Endpoints

### 1. `/search-api` - Web Search
Search the web using multiple engines and get structured results.

**Example:**
```bash
curl "https://your-app.onrender.com/search-api?query=weather&categories=general"
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

### 2. `/fetch` - Content Extraction ⭐ ENHANCED
Extract clean, readable content from any webpage with **Firecrawl-like quality**.

**New Features:**
- 🎯 **Trafilatura extraction** - Better accuracy than basic parsers
- 📝 **Markdown output** - Get structured markdown like Firecrawl
- 📊 **Rich metadata** - Authors, dates, site names automatically extracted
- ⚡ **Still fast** - No browser overhead, pure parsing speed

**Example (Markdown output):**
```bash
curl "https://your-app.onrender.com/fetch?url=https://example.com&format=markdown"
```

**Example (Better text extraction):**
```bash
curl "https://your-app.onrender.com/fetch?url=https://example.com&extraction_mode=trafilatura"
```

**Parameters:**
- `url` (required) - URL to fetch
- `format` - Output format: `text`, `markdown`, or `html` (default: text)
- `extraction_mode` - Engine: `trafilatura` (best quality) or `readability` (faster)
- `include_links` - Include extracted links (default: true)
- `include_images` - Include images (default: true)
- `max_content_length` - Max content length (default: 100000)

**Response:**
```json
{
  "success": true,
  "url": "https://example.com",
  "status_code": 200,
  "metadata": {
    "title": "Example Article",
    "author": "John Doe",
    "date": "2024-01-15",
    "sitename": "Example Site",
    "description": "Article description",
    "language": "en"
  },
  "content": "# Example Article\n\nClean markdown content...",
  "stats": {
    "content_length": 5420,
    "word_count": 890,
    "extraction_mode": "trafilatura",
    "format": "markdown"
  },
  "headings": [...],
  "links": [...],
  "images": [...]
}
```

### 3. `/search-and-fetch` - Search & Auto-Fetch Content ⭐ ENHANCED
**The most powerful endpoint!** Searches and automatically fetches full content with **Trafilatura quality**.

**Example:**
```bash
curl "https://your-app.onrender.com/search-and-fetch?query=python+tutorials&num_results=3&format=markdown"
```

**What it does:**
- ✅ Searches for your query
- ✅ Gets top N results (default: 3, max: 5)
- ✅ Automatically fetches full content from each URL (parallel)
- ✅ Uses **Trafilatura** for Firecrawl-quality extraction
- ✅ Supports markdown, text, or HTML output
- ✅ Returns both search snippets AND full webpage content
- ✅ Handles errors gracefully if a page can't be fetched

**Response:**
```json
{
  "query": "python tutorials",
  "num_results_requested": 3,
  "num_results_found": 3,
  "successful_fetches": 2,
  "failed_fetches": 1,
  "results": [
    {
      "search_result": {
        "title": "Python Tutorial - W3Schools",
        "url": "https://example.com",
        "snippet": "Learn Python...",
        "engine": "google"
      },
      "fetch_status": "success",
      "fetched_content": {
        "title": "Python Tutorial",
        "content": "Full clean article text here...",
        "headings": [
          {"level": "h1", "text": "Introduction to Python"}
        ],
        "content_length": 12500
      }
    }
  ],
  "suggestions": ["python tutorial for beginners"]
}
```

**Parameters:**
- `query` (required) - Search query
- `num_results` (optional) - Number of results to fetch (1-5, default: 3)
- `format` (optional) - Output format: text, markdown, html (default: markdown)
- `categories` (optional) - Search categories (default: general)
- `language` (optional) - Language code (default: en)
- `max_content_length` (optional) - Max content per page (default: 100000)

### 4. `/health` - Health Check
```bash
curl https://your-app.onrender.com/health
```

### 5. `/docs` - Interactive API Documentation
Visit `https://your-app.onrender.com/docs` for Swagger UI

## 🚢 Quick Deploy to Render

### 1. Push to GitHub
```bash
cd miyami_search_api
git add .
git commit -m "Deploy to Render"
git push origin main
```

### 2. Deploy on Render
1. Go to [render.com](https://render.com) and sign in with GitHub
2. Click **New +** → **Web Service**
3. Select your repository
4. Render auto-detects Docker and deploys!

Your API will be live at `https://your-app.onrender.com` in 5 minutes! 🎉

See [RENDER_DEPLOYMENT.md](RENDER_DEPLOYMENT.md) for detailed instructions.

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
python3 -m searx.webapp
```

2. **Start FastAPI** (in another terminal):
```bash
cd search_api
pip install -r requirements.txt
python main.py
```

Access FastAPI at: `http://localhost:8001`

## 🤖 How to Use with AI

### 🔗 Your Live API URL
Replace `your-app-name` with your actual Render app name:
```
https://miyami-websearch-tool.onrender.com
```

### 🛠️ Three Main Tools for AI Agents

#### **Tool 1: Web Search** (`/search-api`)
Search the internet and get relevant results.

**When to use:** When AI needs current information, facts, news, or general web search.

**MCP Tool Definition:**
```json
{
  "name": "web_search",
  "description": "Search the web using multiple search engines (DuckDuckGo, Google, Bing, Brave, Wikipedia). Returns current information from the internet.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "description": "The search query"
      },
      "categories": {
        "type": "string",
        "description": "Search categories: general, news, images, videos (default: general)"
      }
    },
    "required": ["query"]
  }
}
```

**Example Usage:**
```bash
# Search for current information
curl "https://miyami-websearch-tool.onrender.com/search-api?query=latest+AI+news"

# Search with specific category
curl "https://miyami-websearch-tool.onrender.com/search-api?query=python+tutorials&categories=general"
```

**Python Implementation:**
```python
import httpx

async def web_search(query: str, categories: str = "general"):
    """Search the web for current information"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            "https://miyami-websearch-tool.onrender.com/search-api",
            params={"query": query, "categories": categories}
        )
        return response.json()

# Usage
results = await web_search("weather in Tokyo")
print(f"Found {results['number_of_results']} results")
for result in results['results'][:5]:
    print(f"- {result['title']}: {result['url']}")
```

---

#### **Tool 2: Fetch & Extract Content** (`/fetch`)
Fetch any webpage and extract clean, readable content.

**When to use:** When AI needs to read full articles, documentation, or webpage content.

**MCP Tool Definition:**
```json
{
  "name": "fetch_webpage",
  "description": "Fetch and extract clean content from any webpage. Returns the main article text, headings, links, and images without ads or navigation clutter.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "url": {
        "type": "string",
        "description": "The URL to fetch and extract content from"
      },
      "include_links": {
        "type": "boolean",
        "description": "Include extracted links (default: true)"
      }
    },
    "required": ["url"]
  }
}
```

**Example Usage:**
```bash
# Fetch and clean webpage content
curl "https://miyami-websearch-tool.onrender.com/fetch?url=https://example.com/article"

# Fetch with links
curl "https://miyami-websearch-tool.onrender.com/fetch?url=https://example.com&include_links=true"
```

**Python Implementation:**
```python
import httpx

async def fetch_webpage(url: str, include_links: bool = True):
    """Fetch and extract clean content from a webpage"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            "https://miyami-websearch-tool.onrender.com/fetch",
            params={"url": url, "include_links": include_links}
        )
        return response.json()

# Usage
content = await fetch_webpage("https://example.com/article")
print(f"Title: {content['metadata']['title']}")
print(f"Content: {content['content'][:500]}...")
```

---

#### **Tool 3: Search & Auto-Fetch** (`/search-and-fetch`) ⭐ **RECOMMENDED**
Search and automatically fetch full content from top N results in one request.

**When to use:** When AI needs comprehensive research - combines search + fetch for maximum efficiency.

**MCP Tool Definition:**
```json
{
  "name": "search_and_fetch",
  "description": "Search the web and automatically fetch full content from top N results. Perfect for research tasks - gets both search snippets and full article content in one request.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "description": "The search query"
      },
      "num_results": {
        "type": "integer",
        "description": "Number of results to fetch full content from (1-5, default: 3)"
      },
      "categories": {
        "type": "string",
        "description": "Search categories: general, news, images, videos (default: general)"
      }
    },
    "required": ["query"]
  }
}
```

**Example Usage:**
```bash
# Search and fetch top 3 results
curl "https://miyami-websearch-tool.onrender.com/search-and-fetch?query=python+tutorials&num_results=3"

# Research task with news category
curl "https://miyami-websearch-tool.onrender.com/search-and-fetch?query=AI+breakthroughs&categories=news&num_results=5"
```

**Python Implementation:**
```python
import httpx

async def search_and_fetch(query: str, num_results: int = 3, categories: str = "general"):
    """Search and fetch full content from top results"""
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(
            "https://miyami-websearch-tool.onrender.com/search-and-fetch",
            params={"query": query, "num_results": num_results, "categories": categories}
        )
        return response.json()

# Usage
results = await search_and_fetch("quantum computing", num_results=3)
print(f"Found {results['num_results_found']} results")
print(f"Successfully fetched: {results['successful_fetches']}")
for item in results['results']:
    if item['fetch_status'] == 'success':
        print(f"\n{item['search_result']['title']}")
        print(f"Content: {item['fetched_content']['content'][:500]}...")
```

---

### 🎯 Complete AI Workflow Example

```python
import httpx

async def ai_research_assistant(topic: str):
    """
    AI research workflow:
    1. Search for topic
    2. Fetch top results
    3. Extract and summarize content
    """
    base_url = "https://miyami-websearch-tool.onrender.com"
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Step 1: Search the web
        search_response = await client.get(
            f"{base_url}/search-api",
            params={"query": topic, "categories": "general"}
        )
        search_data = search_response.json()
        
        print(f"Found {search_data['number_of_results']} results for '{topic}'")
        
        # Step 2: Fetch content from top 3 results
        articles = []
        for result in search_data['results'][:3]:
            try:
                fetch_response = await client.get(
                    f"{base_url}/fetch",
                    params={"url": result['url'], "include_links": False}
                )
                article = fetch_response.json()
                articles.append({
                    "title": article['metadata']['title'],
                    "url": result['url'],
                    "content": article['content'][:1000]  # First 1000 chars
                })
            except:
                continue
        
        return {
            "search_results": search_data['results'][:5],
            "detailed_articles": articles
        }

# Usage
research = await ai_research_assistant("quantum computing breakthroughs")
```

### 🤖 Example with OpenAI Function Calling

```python
import openai
import httpx

tools = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for current information using multiple search engines",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_webpage",
            "description": "Fetch and extract clean content from a webpage",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to fetch"}
                },
                "required": ["url"]
            }
        }
    }
]

async def execute_function(name: str, arguments: dict):
    base_url = "https://miyami-websearch-tool.onrender.com"
    async with httpx.AsyncClient() as client:
        if name == "web_search":
            response = await client.get(f"{base_url}/search-api", params=arguments)
        elif name == "fetch_webpage":
            response = await client.get(f"{base_url}/fetch", params=arguments)
        return response.json()
```

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
│  - /health              │
└──────┬──────────────────┘
       │ HTTP (internal)
       ↓
┌─────────────────────────┐
│  SearXNG (Port 8888)    │
│  - Multiple engines     │
│  - Result aggregation   │
└─────────────────────────┘
```

## ⚙️ Configuration

### Environment Variables
- `PORT`: API port (default: 8080)
- `SEARXNG_DEBUG`: Debug mode (0 or 1)
- `SEARXNG_SECRET`: Secret key for SearXNG
- `SEARXNG_BIND_ADDRESS`: SearXNG bind address

### SearXNG Settings
Edit `searxng_settings.yml` to configure:
- Search engines
- Request timeouts
- UI settings
- Plugins

## 📈 Monitoring

View logs and metrics on Render Dashboard:
- Real-time logs with search & filtering
- CPU, Memory, and Request metrics
- Deployment history and events

## 🔒 Security Notes

- SearXNG runs on localhost only (127.0.0.1:8888)
- Only FastAPI is exposed to the internet
- No data is logged or stored
- Privacy-focused search (via SearXNG)

## 🆓 Free Tier Details

Render free tier:
- 750 hours/month (enough for 24/7)
- 512 MB RAM
- 100 GB bandwidth/month
- Auto HTTPS (free SSL)
- Spins down after 15 min inactivity
- 30-60s cold start time

Perfect for LLM search tools with moderate usage!

## 🛟 Troubleshooting

**App not responding?**
- Check logs in Render Dashboard → Logs tab
- Check if service spun down (free tier)

**Out of memory?**
- Upgrade to Starter plan ($7/month) for more RAM
- Or optimize Docker image

**Slow first request?**
- Normal on free tier - app wakes from sleep
- Takes 30-60 seconds (SearXNG initialization)
- Use uptime monitor to keep it active

See [RENDER_DEPLOYMENT.md](RENDER_DEPLOYMENT.md) for detailed troubleshooting.

## 📝 License

This project uses:
- SearXNG: AGPL-3.0 License
- FastAPI: MIT License

## 🤝 Contributing

Feel free to:
- Report issues
- Suggest features
- Submit pull requests

## 📚 Resources

- [SearXNG Documentation](https://docs.searxng.org/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Render Documentation](https://render.com/docs)

## 🎯 Use Cases

- LLM web search tools
- AI assistants with internet access
- Automated research tools
- Content aggregation
- Privacy-focused search API

---

Built with ❤️ for the LLM community
