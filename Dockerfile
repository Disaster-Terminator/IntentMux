FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY config ./config
COPY router ./router
COPY scripts ./scripts
COPY README.md ./

ENV PYTHONUNBUFFERED=1
ENV ROUTER_HOST=0.0.0.0
ENV ROUTER_PORT=4001

EXPOSE 4001

HEALTHCHECK --interval=15s --timeout=5s --retries=3 CMD ["uv", "run", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4001/health', timeout=3).read()"]

CMD ["uv", "run", "python", "-m", "router.app"]

