FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv for faster dependency management
RUN pip install --no-cache-dir uv

COPY . .

# Install Python dependencies using uv sync
RUN uv sync --frozen --no-dev --extra disk

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash app \
    && chown -R app:app /app

# Give read and write access to the store_creds volume
RUN mkdir -p /app/store_creds \
    && chown -R app:app /app/store_creds \
    && chmod 755 /app/store_creds

USER app

# Expose port (use default of 8000 if PORT not set)
EXPOSE 8000
ARG PORT
EXPOSE ${PORT:-8000}

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD sh -c 'curl -f http://localhost:${PORT:-8000}/health || exit 1'

# --- Loma deployment config (baked so it survives Railway env-var staging quirks) ---
ENV MCP_ENABLE_OAUTH21=true
ENV WORKSPACE_MCP_BASE_URI=https://loma-gmail-oversight.up.railway.app
ENV WORKSPACE_EXTERNAL_URL=https://loma-gmail-oversight.up.railway.app
ENV WORKSPACE_MCP_ALLOWED_CLIENT_REDIRECT_URIS=https://claude.ai/api/mcp/auth_callback,https://claude.com/api/mcp/auth_callback
ENV WORKSPACE_MCP_BRAND_NAME="Loma GSB Mail"
# Placeholder Google creds so the server boots in OAuth 2.1 mode; override with the real Web client via Railway variables
ENV GOOGLE_OAUTH_CLIENT_ID=000000000000-replaceme.apps.googleusercontent.com
ENV GOOGLE_OAUTH_CLIENT_SECRET=REPLACE_ME

# Set environment variables for Python startup args
ENV TOOL_TIER=""
ENV TOOLS=gmail

# Use entrypoint for the base command and CMD for args
ENTRYPOINT ["/bin/sh", "-c"]
CMD ["uv run main.py --transport streamable-http ${TOOL_TIER:+--tool-tier \"$TOOL_TIER\"} ${TOOLS:+--tools $TOOLS}"]
