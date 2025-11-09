# SearXNG Search API for LLMs

A production-ready FastAPI wrapper for SearXNG that provides LLM-friendly search and web content extraction capabilities.

## 🚀 Features

- **🔍 Web Search API**: Search using multiple search engines via SearXNG
- **📄 Content Extraction**: Fetch and clean webpage content
- **⚡ Fast & Async**: Built with FastAPI and async/await
- **🐳 Docker Ready**: One-command deployment
- **☁️ Cloud Deploy**: Pre-configured for Fly.io
- **🆓 Free Hosting**: Runs on Fly.io free tier
- **🤖 LLM Optimized**: Clean JSON responses perfect for LLM consumption

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
curl "https://your-app.fly.dev/search-api?query=weather&categories=general"
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

### 2. `/fetch` - Content Extraction
Extract clean, readable content from any webpage.

**Example:**
```bash
curl "https://your-app.fly.dev/fetch?url=https://example.com"
```

**Response:**
```json
{
  "metadata": {
    "title": "Example Domain",
    "url": "https://example.com",
    "status_code": 200
  },
  "content": "Clean extracted text...",
  "headings": [...],
  "links": [...],
  "images": [...]
}
```

### 3. `/health` - Health Check
```bash
curl https://your-app.fly.dev/health
```

### 4. `/docs` - Interactive API Documentation
Visit `https://your-app.fly.dev/docs` for Swagger UI

## 🚢 Quick Deploy to Fly.io

### 1. Install Fly.io CLI
```bash
# macOS
brew install flyctl

# Linux
curl -L https://fly.io/install.sh | sh
```

### 2. Login/Signup
```bash
flyctl auth signup
# or
flyctl auth login
```

### 3. Deploy
```bash
cd miyami_search_api
flyctl launch
# Follow prompts, then:
flyctl deploy
```

Your API will be live at `https://your-app-name.fly.dev` 🎉

See [DEPLOYMENT.md](DEPLOYMENT.md) for detailed instructions.

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

## 🤖 LLM Integration

### Example with OpenAI Function Calling

```python
import httpx

tools = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web using multiple search engines",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"}
                },
                "required": ["query"]
            }
        }
    }
]

async def web_search(query: str):
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://your-app.fly.dev/search-api",
            params={"query": query}
        )
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

View logs on Fly.io:
```bash
flyctl logs
```

View metrics:
```bash
flyctl dashboard
```

## 🔒 Security Notes

- SearXNG runs on localhost only (127.0.0.1:8888)
- Only FastAPI is exposed to the internet
- No data is logged or stored
- Privacy-focused search (via SearXNG)

## 🆓 Free Tier Limits

Fly.io free tier:
- 3 shared VMs (256MB RAM each)
- 160GB outbound transfer/month
- Auto-sleep when idle
- Auto-wake on request

This is perfect for LLM search tools with moderate usage.

## 🛟 Troubleshooting

**App not responding?**
- Check logs: `flyctl logs`
- Restart: `flyctl apps restart`

**Out of memory?**
- Scale up: `flyctl scale vm shared-cpu-1x --memory 1024`

**Slow first request?**
- Normal - app wakes from sleep
- Takes 10-20 seconds

See [DEPLOYMENT.md](DEPLOYMENT.md) for more troubleshooting.

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
- [Fly.io Documentation](https://fly.io/docs/)

## 🎯 Use Cases

- LLM web search tools
- AI assistants with internet access
- Automated research tools
- Content aggregation
- Privacy-focused search API

---

Built with ❤️ for the LLM community
