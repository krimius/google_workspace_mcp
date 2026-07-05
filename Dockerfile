FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY . .

RUN uv sync --frozen --no-dev --extra disk

RUN useradd --create-home --shell /bin/bash app \
    && chown -R app:app /app

RUN mkdir -p /app/store_creds \
    && chown -R app:app /app/store_creds \
    && chmod 755 /app/store_creds

USER app

EXPOSE 8000
ARG PORT
EXPOSE ${PORT:-8000}

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD sh -c 'curl -f http://localhost:${PORT:-8000}/health || exit 1'

# --- Loma deployment config (baked; real working Railway domain is the -2fcb one) ---
ENV MCP_ENABLE_OAUTH21=true
ENV WORKSPACE_MCP_BASE_URI=https://gmail-mcp-production-2fcb.up.railway.app
ENV WORKSPACE_EXTERNAL_URL=https://gmail-mcp-production-2fcb.up.railway.app
ENV WORKSPACE_MCP_ALLOWED_CLIENT_REDIRECT_URIS=https://claude.ai/api/mcp/auth_callback,https://claude.com/api/mcp/auth_callback
ENV WORKSPACE_MCP_BRAND_NAME="Loma GSB Mail"
ENV GOOGLE_OAUTH_CLIENT_ID=000000000000-replaceme.apps.googleusercontent.com
ENV GOOGLE_OAUTH_CLIENT_SECRET=REPLACE_ME

ENV TOOL_TIER=""
ENV TOOLS=gmail

ENTRYPOINT ["/bin/sh", "-c"]
CMD ["uv run main.py --transport streamable-http ${TOOL_TIER:+--tool-tier \"$TOOL_TIER\"} ${TOOLS:+--tools $TOOLS}"]
