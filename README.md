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

This repository is intentionally separate from `/path/to/gateway/litellm`.
Do not add LiteLLM mount files, tokens, or `.env` material here.

## Local Run

```bash
uv run python -m router.app
```

## Container Lifecycle

The router is packaged with `Dockerfile` and is intended to run as a sibling
service in the LiteLLM compose project, not as an ad-hoc local process.

The compose service should use:

- build context: `/path/to/gateway/gateway-semantic-router`
- upstream LiteLLM URL: `http://litellm:4000`
- embedding URL from container to host LM Studio:
  `http://host.docker.internal:1234/v1/embeddings`
- exposed router port: `4001`

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

## Semantic Assets

Runtime routing stays dependency-light. Larger semantic assets are built offline
from declared sources in `config/route_sources.yaml`.

The initial source manifest references mature datasets rather than hand-written
keyword expansion:

- MASSIVE zh-CN / zh-TW for general assistant and utility utterances.
- SWE-bench issue statements for repository-level software engineering tasks.
- MBPP and HumanEval for code-generation prompts.
- Local JSONL samples for model-probe traffic.

Build dependencies are isolated from runtime:

```bash
uv sync --group assets
uv run python scripts/build_route_bank.py
```

Generated route banks should retain each utterance's source name so eval
failures remain auditable.
