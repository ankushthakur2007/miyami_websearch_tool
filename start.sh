#!/bin/bash
set -e

echo "Starting SearXNG Search API services..."

# Start SearXNG in the background
cd /app/searxng
echo "Starting SearXNG on 127.0.0.1:8888..."
python3 -m searx.webapp &
SEARXNG_PID=$!

# Wait for SearXNG to be ready (increase timeout for slower Render startup)
echo "Waiting for SearXNG to start..."
SEARXNG_READY=false
for i in {1..60}; do
    if curl -s http://127.0.0.1:8888 > /dev/null 2>&1; then
        echo "SearXNG is ready!"
        SEARXNG_READY=true
        break
    fi
    echo "Waiting for SearXNG... ($i/60)"
    sleep 3
done

if [ "$SEARXNG_READY" = false ]; then
    echo "WARNING: SearXNG did not start in time, but continuing anyway..."
    echo "The service will be available once SearXNG finishes starting."
fi

# Start FastAPI on the PORT provided by Render
cd /app/search_api
echo "Starting FastAPI on 0.0.0.0:${PORT:-8080}..."
exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}
