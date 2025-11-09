#!/bin/bash
set -e

echo "Starting SearXNG Search API services..."

# Generate secret key if not set
export SEARXNG_SECRET="${SEARXNG_SECRET:-$(openssl rand -hex 32)}"
export SEARXNG_BIND_ADDRESS="${SEARXNG_BIND_ADDRESS:-127.0.0.1}"
export SEARXNG_PORT="${SEARXNG_PORT:-8888}"

# Start SearXNG in the background
cd /app/searxng
echo "Starting SearXNG on ${SEARXNG_BIND_ADDRESS}:${SEARXNG_PORT}..."
echo "Using settings from: searx/settings.yml"

# Run SearXNG with proper error handling
python3 -m searx.webapp 2>&1 | tee /tmp/searxng.log &
SEARXNG_PID=$!

# Wait for SearXNG to be ready (increase timeout for slower Render startup)
echo "Waiting for SearXNG to start..."
SEARXNG_READY=false
for i in {1..60}; do
    if curl -s http://${SEARXNG_BIND_ADDRESS}:${SEARXNG_PORT} > /dev/null 2>&1; then
        echo "SearXNG is ready!"
        SEARXNG_READY=true
        break
    fi
    echo "Waiting for SearXNG... ($i/60)"
    
    # Check if SearXNG process died
    if ! kill -0 $SEARXNG_PID 2>/dev/null; then
        echo "ERROR: SearXNG process died! Showing last 20 lines of log:"
        tail -n 20 /tmp/searxng.log
        exit 1
    fi
    
    sleep 3
done

if [ "$SEARXNG_READY" = false ]; then
    echo "WARNING: SearXNG did not start in time. Showing last 30 lines of log:"
    tail -n 30 /tmp/searxng.log
    echo "Continuing anyway - the service may become available later..."
fi

# Start FastAPI on the PORT provided by Render
cd /app/search_api
echo "Starting FastAPI on 0.0.0.0:${PORT:-8080}..."
exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}
