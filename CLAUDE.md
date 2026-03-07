# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Architecture Overview

This is a **SearXNG-powered search API** with two main components:

### SearXNG (Meta-Search Engine)
- Self-hosted meta-search engine running on port 8888
- Aggregates results from: DuckDuckGo, Google, Bing, Brave, Startpage, Wikipedia
- Configuration: `searxng_settings.yml`
- Started via `start.sh` before the FastAPI app

### FastAPI Wrapper (`search_api/`)
- Runs on port 8080 (Docker) or 8001 (local dev)
- Provides LLM-optimized endpoints with consistent JSON/Markdown output

## Core Modules

| File | Purpose |
|------|---------|
| `main.py` | FastAPI app with 8+ endpoints; integrates all submodules |
| `stealth_client.py` | Anti-bot bypass with TLS fingerprinting (curl_cffi) |
| `antibot.py` | Detects Cloudflare, reCAPTCHA, hCaptcha, DataDome, Akamai, PerimeterX, Imperva, Kasada |
| `scrapy_crawler.py` | Scrapy spider for recursive site crawling |
| `stealth_middleware.py` | Scrapy middleware integrating stealth client |
| `document_extractor.py` | Auto-detects and extracts text from PDF, DOCX, XLSX, PPTX, MD, RTF, CSV |

## Key Architecture Decisions

1. **Async First**: All HTTP clients use `httpx.AsyncClient` for performance
2. **Compression Handling**: Custom `decompress_content()` handles gzip, deflate, brotli
3. **Encoding Fallback**: Multi-encoding detection (UTF-8, Latin-1, CP1252, etc.)
4. **Stealth Levels**: `off` → `low` (UA rotation) → `medium` (UA+headers) → `high` (TLS fingerprint)
5. **Auto-bypass**: Automatically escalates stealth levels when protections detected
6. **Caching**: DiskCache for search results (1-hour TTL)
7. **AI Reranking**: FlashRank with `ms-marco-TinyBERT-L-2-v2` model
8. **Document Extraction**: Auto-detects documents by URL extension or Content-Type header

## Document Auto-Fetch Feature

The `/fetch` endpoint automatically detects and extracts text from document files:

**Supported Formats:**
- PDF (via `pypdf`)
- Word/DOCX (via `python-docx`)
- Excel/XLSX (via `openpyxl`)
- PowerPoint/PPTX (via `python-pptx`)
- Markdown (raw text)
- RTF (text extraction)
- CSV (via `csv` module)
- TXT (raw text)

**Detection Logic:**
1. Checks URL extension (`.pdf`, `.docx`, `.xlsx`, `.pptx`, `.md`, `.rtf`, `.csv`, `.txt`)
2. Falls back to Content-Type header matching

**Response Format:**
```json
{
  "success": true,
  "url": "https://example.com/file.pdf",
  "is_document": true,
  "document_type": "pdf",
  "content": "Extracted text content...",
  "stats": {
    "content_length": 1234,
    "word_count": 250,
    "document_type": "pdf"
  }
}
```

## Development Setup

```bash
# Terminal 1: Start SearXNG
cd searxng
export PYTHONPATH="$PWD:$PYTHONPATH"
python3 -m searx.webapp

# Terminal 2: Start FastAPI
cd search_api
pip install -r requirements.txt
uvicorn main:app --reload --port 8001
```

## Running Tests

No test suite currently exists. To add tests, use `pytest`:

```bash
pip install pytest pytest-asyncio
pytest search_api/
```

## Common Tasks

- **Add new endpoint**: Add to `main.py` with `@app.get()` decorator, use existing patterns
- **Modify search behavior**: Adjust params in `search_api()` function (lines 1179+)
- **Update stealth mode**: Modify `StealthLevel` enum and browser user agents in `stealth_client.py`
- **Add protection detection**: Extend patterns in `antibot.py`
- **Add new document format**: Update `document_extractor.py` with new extraction function
