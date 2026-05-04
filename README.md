# Gateway Semantic Router

Lightweight OpenAI-compatible sidecar for `/v1/chat/completions`.

It rewrites the configured semantic entry model, currently
`model=semantic-router`, into the local LiteLLM groups:

- `cheap-router`
- `pro-router`
- `free-probe-router`

Runtime config validation enforces that rewritten targets stay inside those
three groups. The semantic entry model itself cannot appear as a target route or
default route, which prevents recursive forwarding back to `semantic-router`.

All other model names pass through unchanged. LiteLLM's native `smart-router`
is intentionally kept as a separate upstream model group.

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
- `ROUTER_LITELLM_TIMEOUT`
- `ROUTER_EMBEDDING_URL`
- `ROUTER_EMBEDDING_MODEL`
- `ROUTER_ACCESS_LOG` (`false` by default; set `true` only when raw HTTP
  access logs are needed)
- `ROUTER_READINESS_TIMEOUT`

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

## CI

GitHub Actions CI validates baseline pull request safety checks only:

- `uv run python -m pytest -q`
- `uv run python scripts/eval_routes.py --mock-embeddings`

CI does **not** claim full production validation. Live preflight, LiteLLM-entry
E2E checks, Docker log review, and route-error budget checks remain
operator/local-production checks.

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
It checks liveness, layered readiness, non-streaming route headers, streaming
route headers, and SSE body shape without printing secrets or prompts. When
readiness is degraded, it prints the degraded component detail, for example
`ready=False degraded=embedding:ConnectError`. Readiness is retried briefly by
default; use `--ready-attempts` and `--ready-interval` to tune that gate.

Runtime probes:

- `/health` is a local liveness check for container health.
- `/ready` is a layered readiness check. It reports `router`, `litellm`, and
  `embedding` components separately and returns `503` when any layer is
  degraded. Docker health intentionally still uses `/health` so readiness can be
  observed without causing restart loops.

Embedding degraded mode is intentionally fail-open for routed chat requests:
when the embedding component is unavailable, `/ready` returns `503`, but
`model=semantic-router` requests fall back to `default_route` with
`reason=embedding_error`. LiteLLM/upstream proxy failures are different: they
fail closed as redacted `502` responses and are logged as `route_error`.

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

Within the sidecar, route logs include both `request_id` and
`request_id_source`. The sidecar accepts `x-request-id`, `x-correlation-id`,
W3C `traceparent`, `metadata.semantic_router_request_id`, and `user` as request
identity sources, then injects the final value into the upstream `x-request-id`
header. This makes sidecar-to-upstream correlation stable even when LiteLLM's
model-entry layer does not preserve the original client id.

Production route-log summary from sidecar logs:

```bash
docker logs --since 12h gateway_semantic_router 2>&1 \
  | uv run python scripts/router_log_summary.py
```

The summary parser ignores uvicorn access lines and only counts structured
`route_complete` / `route_error` JSON records. Upstream route exceptions and
HTTP `5xx` statuses are returned as `502` with a redacted JSON error body and
are logged as `route_error`; HTTP status failures include `upstream_status` in
the structured log and `upstream_statuses` in the summary. Route reasons are
also counted, so degraded embedding fallback shows up as
`reasons: embedding_error=N`. Prompts and bearer tokens are not logged.
When malformed JSON, missing-event JSON records, or unknown-event JSON records
are present after the first `{` in a log line, the summary adds an
`ignored_records` line so operators can distinguish parser/log-shape drift from
real routed traffic. Plain access-log lines without JSON objects are still
ignored silently.

Production route-error budget gate:

```bash
docker logs --since 12h gateway_semantic_router 2>&1 \
  | uv run python scripts/check_route_error_budget.py \
      --min-total 1 \
      --max-error-rate 0 \
      --max-target-error-rate 0 \
      --max-reason-rate embedding_error=0
```

The budget gate prints a stable PASS/FAIL report and exits non-zero when the
selected log window has too few route events or exceeds the total/per-target
`route_error` thresholds. Optional `--max-reason-rate REASON=RATE` checks
bounded degradation such as `embedding_error` fallback even when requests still
complete. Use this after preflight/E2E and before keeping a new router build in
production traffic.

For a live sidecar request, pass the same LiteLLM `Authorization` header to
`http://127.0.0.1:4001/v1/chat/completions`.

Routing decision preview without upstream forwarding:

```bash
curl http://127.0.0.1:4001/v1/semantic-router/decision \
  -H "Content-Type: application/json" \
  -d '{"model":"semantic-router","messages":[{"role":"user","content":"这个线上 bug 为什么偶发？"}]}'
```

Use this endpoint for route quality review and gray-mode evaluation. It returns
the selected target, reason, rewrite flag, and scores, but does not call LiteLLM
or any model backend.

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

Redacted production review samples can be promoted into eval cases without
putting raw prompts in logs or git:

```bash
uv run python scripts/import_review_samples.py \
  --input data/source_samples/production_review.redacted.jsonl \
  --output data/semantic_sets/production_review_eval_cases.yaml

uv run python scripts/build_eval_bank.py \
  --manual-cases data/semantic_sets/production_review_eval_cases.yaml \
  --per-route-limit 100
```

Each JSONL sample must set `redacted: true`, include `text`, and set `expect`
to one of `cheap-router`, `pro-router`, or `free-probe-router`. The importer
rejects unredacted samples by default.
