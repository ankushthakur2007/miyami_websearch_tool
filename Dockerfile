# Use Python 3.11 slim image
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    git \
    build-essential \
    libxml2-dev \
    libxslt1-dev \
    zlib1g-dev \
    libffi-dev \
    libssl-dev \
    unzip \
    valkey-server \
    && rm -rf /var/lib/apt/lists/*

# Install Deno (required by yt-dlp for JavaScript execution)
RUN curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh
ENV PATH="/usr/local/bin:${PATH}"

# Set working directory
WORKDIR /app

# Copy SearXNG source (now part of repo) AND .git for version detection
COPY searxng /app/searxng
COPY .git /app/searxng/.git

# Install SearXNG dependencies
WORKDIR /app/searxng
RUN pip install --no-cache-dir -r requirements.txt

# Copy SearXNG limiter config
RUN mkdir -p /etc/searxng
COPY searxng/searx/limiter.toml /etc/searxng/limiter.toml

# Copy FastAPI application
WORKDIR /app
COPY search_api /app/search_api

# Install FastAPI dependencies
RUN pip install --no-cache-dir -r /app/search_api/requirements.txt

# Copy startup script
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

# Expose ports
EXPOSE 8080

# Set environment variables
ENV SEARXNG_DEBUG=0 \
    SEARXNG_BIND_ADDRESS="127.0.0.1" \
    SEARXNG_PORT=8888 \
    PORT=8080 \
    SEARXNG_VALKEY_URL="valkey://localhost:6379/0" \
    SEARXNG_LIMITER=true

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Start both services
CMD ["/app/start.sh"]
