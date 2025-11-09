#!/bin/bash
set -e

echo "Starting SearXNG Search API services..."

# Start SearXNG in the background
cd /app/searxng
echo "Starting SearXNG on 127.0.0.1:8888..."
python3 -m searx.webapp &
SEARXNG_PID=$!

# Wait for SearXNG to be ready
echo "Waiting for SearXNG to start..."
for i in {1..30}; do
    if curl -s http://127.0.0.1:8888 > /dev/null 2>&1; then
        echo "SearXNG is ready!"
        break
    fi
    echo "Waiting for SearXNG... ($i/30)"
    sleep 2
done

# Start FastAPI on the PORT provided by Fly.io
cd /app/search_api
echo "Starting FastAPI on 0.0.0.0:${PORT:-8080}..."
exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}
