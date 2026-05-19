FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app
ENV UV_HTTP_TIMEOUT=120

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY config ./config
COPY router ./router
COPY scripts ./scripts
COPY README.md ./
RUN uv sync --locked --no-dev

ENV PYTHONUNBUFFERED=1
ENV ROUTER_HOST=0.0.0.0
ENV ROUTER_PORT=4001
ENV ROUTER_CONFIG=/app/config/routes.yaml
ENV ROUTER_AUDIT_LOG_ENABLED=true
ENV ROUTER_AUDIT_LOG_DIR=/data/logs/routes
ENV ROUTER_PROMPT_LOG_MODE=off
ENV ROUTER_PROMPT_LOG_DIR=/data/logs/prompts

EXPOSE 4001

HEALTHCHECK --interval=15s --timeout=5s --retries=3 CMD ["uv", "run", "--no-sync", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4001/health', timeout=3).read()"]

CMD ["uv", "run", "--no-sync", "python", "-m", "router.app"]
