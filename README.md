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

## Container Lifecycle

The router is packaged with `Dockerfile` and is intended to run as a sibling
service in the LiteLLM compose project, not as an ad-hoc local process.

It remains a third-party sidecar. Future lifecycle coupling may bind it more
closely to the LiteLLM service readiness/restart lifecycle, but that coupling is
still a design item rather than current behavior. See `docs/roadmap.md`.

The compose service should use:

- build context: `/home/raystorm/gateway/gateway-semantic-router`
- upstream LiteLLM URL: `http://litellm:4000`
- embedding URL from container to host LM Studio:
  `http://host.docker.internal:1234/v1/embeddings`
- exposed router port: `4001`
- optional generated semantic asset mount:
  `/home/raystorm/gateway/gateway-semantic-router/data/semantic_sets:/app/data/semantic_sets:ro`

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

- MASSIVE zh-CN / zh-TW official JSONL tarball for general assistant and
  utility utterances. The current Hugging Face `datasets` loader cannot load
  `AmazonScience/massive` directly because that dataset still uses a dataset
  script, so the builder reads the official release archive instead.
- SWE-bench issue statements for repository-level software engineering tasks.
- MBPP and HumanEval for code-generation prompts.
- Local JSONL samples for model-probe traffic.

Build dependencies are isolated from runtime:

```bash
uv sync --group assets
uv run python scripts/build_route_bank.py
uv run python scripts/build_eval_bank.py --per-route-limit 100
```

Generated route banks should retain each utterance's source name so eval
failures remain auditable.

Runtime loading is conservative: `config/routes.yaml` declares
`route_bank_path: data/semantic_sets/route_bank.yaml`, and `load_settings()`
merges that generated bank with the seed utterances only when the file exists.
If the bank is absent, the router keeps using the checked-in seed routes.

The generated eval bank is also kept out of git. A 200+ case regression run can
be reproduced after building the route bank:

```bash
uv run python scripts/eval_routes.py --cases data/semantic_sets/eval_bank.yaml
```
