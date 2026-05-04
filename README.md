# Gateway Semantic Router

Lightweight OpenAI-compatible sidecar for `/v1/chat/completions`.

It rewrites the configured semantic entry model, currently
`model=semantic-router`, into the local LiteLLM groups:

- `cheap-router`
- `pro-router`
- `free-probe-router`

All other model names pass through unchanged. LiteLLM's native `smart-router`
is intentionally kept as a separate upstream model group.

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

It remains a third-party sidecar. Future lifecycle coupling may bind it more
closely to the LiteLLM service readiness/restart lifecycle, but that coupling is
still a design item rather than current behavior. See `docs/roadmap.md`.

The compose service should use:

- build context: `/path/to/gateway/gateway-semantic-router`
- upstream LiteLLM URL: `http://litellm:4000`
- embedding URL from container to host LM Studio:
  `http://host.docker.internal:1234/v1/embeddings`
- exposed router port: `4001`
- optional generated semantic asset mount:
  `/path/to/gateway/gateway-semantic-router/data/semantic_sets:/app/data/semantic_sets:ro`

Default endpoints:

- Router: `http://127.0.0.1:4001`
- LiteLLM upstream: `http://127.0.0.1:4000`
- Embedding upstream: `http://127.0.0.1:1234/v1/embeddings`

Environment overrides:

- `ROUTER_HOST`
- `ROUTER_PORT`
- `ROUTER_LITELLM_BASE_URL`
- `ROUTER_LITELLM_TIMEOUT`
- `ROUTER_EMBEDDING_URL`
- `ROUTER_EMBEDDING_MODEL`
- `ROUTER_ACCESS_LOG` (`false` by default; set `true` only when raw HTTP
  access logs are needed)

## LiteLLM Entry Design

The low-intrusion production direction is to keep upstream clients on the
LiteLLM base URL and expose the sidecar as a LiteLLM model entry named
`semantic-router`. In that shape, clients keep `http://127.0.0.1:4000` and opt
in by changing only the model name.

LiteLLM's native `smart-router` should remain separate. It continues to mean
LiteLLM's built-in complexity router, while `semantic-router` means this
sidecar's semantic task router.

Current proof and acceptance criteria are documented in
`docs/superpowers/specs/2026-05-03-litellm-semantic-router-entry-design.md`.

## Verification

```bash
uv run python -m pytest -q
uv run python scripts/eval_routes.py --mock-embeddings
```

Production preflight against a running router:

```bash
uv run python scripts/preflight.py --router-base-url http://127.0.0.1:4001
```

The preflight requires `LITELLM_MASTER_KEY` in the environment or `--api-key`.
It checks health, non-streaming route headers, streaming route headers, and SSE
body shape without printing secrets or prompts.

Production E2E through the LiteLLM entrypoint:

```bash
uv run python scripts/e2e_litellm_entry.py --litellm-base-url http://127.0.0.1:4000
```

The E2E checks `model=semantic-router` through LiteLLM `:4000`, verifies
non-streaming and streaming responses, and confirms sidecar route logs for
`pro-router`, `cheap-router`, and `free-probe-router`. LiteLLM's model-entry
path does not currently preserve client-supplied correlation IDs to the sidecar,
so the script first tries request-id matching and then falls back to recent route
shape matching.

Production route-log summary from sidecar logs:

```bash
docker logs --since 12h gateway_semantic_router 2>&1 \
  | uv run python scripts/router_log_summary.py
```

The summary parser ignores uvicorn access lines and only counts structured
`route_complete` / `route_error` JSON records. Upstream route failures are
returned as `502` with a redacted JSON error body and are logged as
`route_error`; prompts and bearer tokens are not logged.

For a live sidecar request, pass the same LiteLLM `Authorization` header to
`http://127.0.0.1:4001/v1/chat/completions`.

Streaming smoke test:

```bash
curl -N http://127.0.0.1:4001/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"semantic-router","stream":true,"messages":[{"role":"user","content":"这个线上 bug 为什么偶发？只回答 OK"}],"max_tokens":8}'
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
