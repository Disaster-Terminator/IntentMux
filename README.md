# Gateway Semantic Router

Lightweight OpenAI-compatible sidecar for `/v1/chat/completions`.

It only rewrites `model=smart-router` requests into the local LiteLLM groups:

- `cheap-router`
- `pro-router`
- `free-probe-router`

All other model names pass through unchanged.

Both non-streaming and `stream=true` SSE chat completions are proxied. The
sidecar rewrites only the request model field, then preserves the upstream
LiteLLM response body and routing headers.

This repository is intentionally separate from `/home/raystorm/gateway/litellm`.
Do not add LiteLLM mount files, tokens, or `.env` material here.

## Local Run

```bash
uv run python -m router.app
```

Default endpoints:

- Router: `http://127.0.0.1:4001`
- LiteLLM upstream: `http://127.0.0.1:4000`
- Embedding upstream: `http://127.0.0.1:1234/v1/embeddings`

Environment overrides:

- `ROUTER_HOST`
- `ROUTER_PORT`
- `ROUTER_LITELLM_BASE_URL`
- `ROUTER_EMBEDDING_URL`
- `ROUTER_EMBEDDING_MODEL`

## Verification

```bash
uv run python -m pytest -q
uv run python scripts/eval_routes.py --mock-embeddings
```

For a live sidecar request, pass the same LiteLLM `Authorization` header to
`http://127.0.0.1:4001/v1/chat/completions`.

Streaming smoke test:

```bash
curl -N http://127.0.0.1:4001/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"smart-router","stream":true,"messages":[{"role":"user","content":"这个线上 bug 为什么偶发？只回答 OK"}],"max_tokens":8}'
```
