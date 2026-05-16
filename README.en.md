# IntentMux

> Lightweight, auditable intent-routing sidecar for LiteLLM.<br>
> Select a `route_id` from request intent, then resolve it to your local LiteLLM model group.

<p align="center">
  <img alt="runtime Python 3.11+" src="https://img.shields.io/badge/runtime-Python%203.11%2B-3776AB">
  <img alt="entry semantic-router" src="https://img.shields.io/badge/entry-semantic--router-0EA5E9">
  <img alt="gateway LiteLLM compatible" src="https://img.shields.io/badge/gateway-LiteLLM%20compatible-16A34A">
  <img alt="route logs metadata only" src="https://img.shields.io/badge/route%20logs-metadata%20only-7C3AED">
</p>
<p align="center">
  <img alt="built with FastAPI" src="https://img.shields.io/badge/built%20with-FastAPI-009688">
  <img alt="config YAML" src="https://img.shields.io/badge/config-YAML-CB171E">
  <img alt="tests pytest" src="https://img.shields.io/badge/tests-pytest-0A9EDC">
  <img alt="package uv" src="https://img.shields.io/badge/package-uv-DE5FE9">
  <img alt="license Apache-2.0" src="https://img.shields.io/badge/license-Apache--2.0-111827">
</p>

[中文](README.md)

## One Line

IntentMux is a local-first OpenAI-compatible / LiteLLM-compatible routing sidecar. Clients keep using the existing LiteLLM endpoint and opt in with `model=semantic-router`; IntentMux selects a `route_id` from request intent, then resolves that route to the deployment-specific `target_model`.

<table>
  <tr>
    <td><strong>Intent routing</strong><br>Route between the default `fast` and `strong` tiers with semantic scores and thresholds.</td>
    <td><strong>Low-intrusion integration</strong><br>Keep LiteLLM responsible for providers, fallback, rate limits, and authentication.</td>
  </tr>
  <tr>
    <td><strong>Auditable logs</strong><br>Route audit logs are metadata-only by default; private local deployments can explicitly enable prompt review logs.</td>
    <td><strong>Operational gates</strong><br>Ship with preflight, LiteLLM-entry E2E, log summaries, and route-error budget checks.</td>
  </tr>
</table>

## Project Boundary

IntentMux is not a model provider and does not replace LiteLLM. It only handles the configured compatibility entry model:

```text
model=semantic-router -> route_id -> target_model -> LiteLLM model group
```

All other model names pass through.

The default sample config uses two product-level route ids, `fast` and `strong`, mapped to LiteLLM model groups such as `cheap-router` and `pro-router`. These `target_model` values are deployment names, not product API names. Custom routes remain supported, but the default product model is a weak/strong two-tier router.

Deploy IntentMux as a sidecar next to LiteLLM and keep provider secrets, tokens, `.env` files, and mounted LiteLLM data outside this repository.

The default router borrows the common strong/weak LLM-router shape and Semantic
Router thresholding:

```text
explicit override -> high-precision hard escalation -> agent structure signal -> semantic score + threshold -> fallback fast
```

`hard_rules` are reserved for high-risk escalation signals such as security,
secret leakage, production incidents, rollbacks, or data corruption. Ambiguous
engineering words such as `PR`, `debug`, deployment, indexing, exceptions, and
errors are handled by semantic examples and thresholds by default, so agent
context accumulation does not permanently pin a conversation to `strong`.

OpenAI-compatible requests with `tools` / legacy `functions`, tool-call history,
`tool_choice`, or long multi-turn context are escalated to `strong` with
`policy_id=agent_signal` by default. This policy uses request structure only; it
does not depend on local framework names such as OpenCode, Hermes, or Retinue.

## Quick Start

```bash
uv run python -m router.app
```

Default endpoints:

| Service | URL |
| --- | --- |
| IntentMux sidecar | `http://127.0.0.1:4001` |
| LiteLLM upstream | `http://127.0.0.1:4000` |
| Embedding upstream | `http://127.0.0.1:1234/v1/embeddings` |

For container deployment, run IntentMux as a LiteLLM sidecar with its own mounted home. This is a generic layout, not a required host path:

```text
litellm/
  docker-compose.yml
  config.yaml
  .env
  intentmux/
    config/routes.yaml
    semantic_sets/route_bank.yaml
    logs/routes/YYYY-MM-DD.jsonl
    logs/prompts/YYYY-MM-DD.jsonl   # optional local-only prompt review log
```

Inside the container, `/app` is image code and `/data` is the user-mounted IntentMux home.

The repository ships a generic compose example: [examples/docker-compose.yml](examples/docker-compose.yml).

```bash
mkdir -p .intentmux-home
cp -R examples/intentmux-home/. .intentmux-home/
docker compose -f examples/docker-compose.yml up -d --build
```

By default, the example mounts `.intentmux-home/` from the repository root to `/data`. That directory is ignored by git and is suitable for local trials. For production, copy [examples/intentmux-home](examples/intentmux-home) outside the source checkout and point `INTENTMUX_HOME=/path/to/intentmux-home` at it.

Common overrides:

- `INTENTMUX_PORT`: host port, default `4001`; the example compose binds it to `127.0.0.1` by default.
- `INTENTMUX_HOME`: host-side IntentMux home, default `../.intentmux-home` relative to `examples/docker-compose.yml`.
- `ROUTER_LITELLM_BASE_URL`: LiteLLM upstream URL, default `http://host.docker.internal:4000`.
- `ROUTER_LITELLM_API_KEY`: dedicated key used by IntentMux when calling upstream LiteLLM. When set, inbound `Authorization` is not forwarded upstream.
- `ROUTER_INBOUND_API_KEY`: optional IntentMux inbound key for `/v1/chat/completions` and `/v1/semantic-router/decision`; `/health` and `/ready` remain unauthenticated.
- `ROUTER_PROMPT_LOG_MODE`: optional prompt review log mode, default `off`; use `redacted` or `raw_local` only for private local review.
- `ROUTER_PROMPT_LOG_DIR`: prompt review log directory. The compose example uses `/data/logs/prompts`.
- `ROUTER_PROMPT_LOG_MAX_CHARS`: maximum latest-user-text characters per prompt review record, default `20000`.
- `ROUTER_EMBEDDING_URL`: embedding upstream URL, default `http://host.docker.internal:1234/v1/embeddings`.
- `ROUTER_EMBEDDING_MODEL`: embedding model name.

See [examples/litellm-model-entry.yaml](examples/litellm-model-entry.yaml) for a LiteLLM entry-model snippet. If IntentMux and LiteLLM share one compose network, `api_base` can be `http://intentmux:4001/v1`; otherwise, set it to the IntentMux URL reachable from LiteLLM.

Auth boundaries:

- The LiteLLM model-entry `api_key` authenticates `LiteLLM -> IntentMux`.
- `ROUTER_INBOUND_API_KEY` protects direct IntentMux sidecar requests.
- `ROUTER_LITELLM_API_KEY` authenticates `IntentMux -> LiteLLM`; inbound `Authorization` is not reused upstream.

Update rules:

- Changes to `/data/config/routes.yaml`, `/data/semantic_sets/route_bank.yaml`, or environment variables require restarting the IntentMux sidecar so startup-loaded config and route vectors refresh.
- Changes to Python code, `Dockerfile`, built-in `config/`, or `examples/` require rebuilding the image and recreating the IntentMux sidecar.
- README, test, and offline-script changes do not affect the running container, but should still be verified with the matching test or check command.

Common compose update flow:

```bash
docker compose -f examples/docker-compose.yml build intentmux
docker compose -f examples/docker-compose.yml up -d intentmux
```

IntentMux does not hot-reload yet; production updates follow the rule: restart for config, rebuild for code.

`examples/intentmux-home/` is a copyable runtime template. Keep LiteLLM `.env`, provider tokens, and databases outside the IntentMux home. If `ROUTER_PROMPT_LOG_MODE=raw_local` is enabled, `/data/logs/prompts` stores prompt review logs for private local review only; do not commit, upload, or attach that directory to public issues.

## LiteLLM Entry

The low-intrusion path is to keep clients on LiteLLM `:4000` and change only the model name to `semantic-router`.

```text
client -> LiteLLM :4000, model=semantic-router
       -> IntentMux :4001
       -> route_id
       -> target_model
       -> LiteLLM model group
```

Configure `semantic-router` in LiteLLM as a model entry that points to the IntentMux sidecar. Requests that use that model name are routed by intent; other model names pass through unchanged.

## Verification

```bash
uv run python -m pytest -q
uv run python scripts/eval_routes.py --mock-embeddings
uv run python scripts/verify_route_contract.py
```

Production preflight:

```bash
uv run python scripts/preflight.py --router-base-url http://127.0.0.1:4001
# If ROUTER_INBOUND_API_KEY is configured:
uv run python scripts/preflight.py \
  --router-base-url http://127.0.0.1:4001 \
  --intentmux-api-key "$ROUTER_INBOUND_API_KEY"
```

LiteLLM-entry E2E:

```bash
uv run python scripts/e2e_litellm_entry.py --litellm-base-url http://127.0.0.1:4000
```

## Log Review

```bash
docker logs --since 12h intentmux 2>&1 \
  | uv run python scripts/router_log_summary.py --slow-request-limit 10

uv run python scripts/router_log_summary.py /data/logs/routes/*.jsonl \
  --slow-request-limit 10

docker logs --since 12h intentmux 2>&1 \
  | uv run python scripts/check_route_error_budget.py \
      --min-total 1 \
      --max-error-rate 0 \
      --max-target-error-rate 0 \
      --max-route-error-rate 0 \
      --max-not-ok-rate 0 \
      --max-embedding-error-rate 0 \
      --max-upstream-status-rate 400=0
```

Summary output includes route/target/reason distributions, `ok/outcome`, upstream status codes, `max_duration_ms`, `p50/p90/p95/p99` duration percentiles, and the slowest request samples. Slow request samples include only audit metadata: timestamp, `request_id`, `route_id`, `target_model`, `reason`, `upstream_status`, and duration.

Structured route audit logs count `route_id`, `target_model`, `policy_id`, `reason`, `request_id`, `request_id_source`, `stream`, `upstream_status`, `ok`, `outcome`, `decision_ms`, and `upstream_ms`, while avoiding prompts, completions, token usage, and bearer tokens. Streaming requests also include `upstream_headers_ms` and `upstream_body_ms`. `event` is lifecycle; `ok/outcome` is route health. Upstream non-2xx responses record `ok=false` and `outcome=upstream_non_200`. `embedding_error` has a dedicated budget shortcut because it can fail open to the configured fast route without making the user request fail.

Private local deployments can explicitly enable a separate prompt review log:

```bash
ROUTER_PROMPT_LOG_MODE=redacted   # mask common bearer/sk/base64 credentials
ROUTER_PROMPT_LOG_MODE=raw_local  # record latest user text as-is for local review
```

Prompt review logs are written to `ROUTER_PROMPT_LOG_DIR/YYYY-MM-DD.jsonl`; they do not go to stdout, route audit JSONL, or daily health reports. Keep this mode off in public or untrusted environments.

The log-driven quality loop is documented in [docs/log_driven_quality_loop.md](docs/log_driven_quality_loop.md). Route audit logs identify low confidence, upstream failures, slow requests, and route distribution drift; prompt review logs are explicit local-only supplemental evidence. Generate metadata-only review candidates with:

```bash
uv run python scripts/select_review_candidates.py /data/logs/routes/*.jsonl \
  --routes /data/config/routes.yaml \
  --json-output /tmp/intentmux-review-candidates.json \
  --markdown-output /tmp/intentmux-review-candidates.md
```

Only human-reviewed samples with `redacted: true` should be promoted into eval cases or route banks. See [data/source_samples/production_review.example.jsonl](data/source_samples/production_review.example.jsonl) for the public sample format.
Real production review JSONL files are ignored by git by default; commit only curated public examples.

## Decision Preview

```bash
curl http://127.0.0.1:4001/v1/semantic-router/decision \
  -H "Content-Type: application/json" \
  -d '{"model":"semantic-router","messages":[{"role":"user","content":"Why is this production bug intermittent?"}]}'
```

If `ROUTER_INBOUND_API_KEY` is enabled, include the inbound auth header:

```bash
curl http://127.0.0.1:4001/v1/semantic-router/decision \
  -H "Authorization: Bearer $ROUTER_INBOUND_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"semantic-router","messages":[{"role":"user","content":"Why is this production bug intermittent?"}]}'
```

This returns the selected `route_id`, resolved `target_model`, `policy_id`, reason, rewrite flag, and scores without forwarding to LiteLLM.

## Semantic Assets

Runtime dependencies stay small. Larger route banks are built offline from the
sources declared in `config/route_sources.yaml`; Hugging Face and dataset tools
are not runtime dependencies.

The repository includes a small tracked example at
[examples/route_bank.sample.yaml](examples/route_bank.sample.yaml). It is for
showing source/license metadata and route-bank shape. Real deployments should
generate or maintain their own `/data/semantic_sets/route_bank.yaml`.

Recommended quality-report flow:

```bash
uv run python scripts/eval_routes.py --mock-embeddings > /tmp/intentmux-eval.txt
uv run python scripts/router_log_summary.py /data/logs/routes/*.jsonl --json > /tmp/intentmux-routes.json
uv run python scripts/route_quality_report.py \
  --eval-output /tmp/intentmux-eval.txt \
  --route-summary-json /tmp/intentmux-routes.json \
  --route-bank examples/route_bank.sample.yaml \
  --json-output /tmp/intentmux-quality.json \
  --markdown-output /tmp/intentmux-quality.md
```

Route-bank, threshold, margin, and hard-rule changes should include this quality
report before production rollout.

For agent frameworks, see
[docs/agent_framework_integration.md](docs/agent_framework_integration.md).
Code-editing agents, tool-call loops, PR review, production incidents, and
security analysis should usually send `metadata.route_id=strong` explicitly
instead of relying only on low-confidence fallback.

## Runtime Behavior

Run IntentMux as a sidecar in the same deployment boundary as LiteLLM.

- Docker health uses `/health` to avoid readiness flapping restart loops.
- `/ready` checks router, LiteLLM, and embedding availability.
- When embeddings are unavailable, chat requests fail open to `fallback_route_id` and log `reason=embedding_error`.
- LiteLLM/upstream `5xx` responses or connection errors fail closed as redacted `502` responses and log `route_error`.
- LiteLLM/upstream `4xx` responses are passed through by proxy semantics, but audit logs mark them as `ok=false` / `outcome=upstream_non_200`.

## Current Capabilities

IntentMux includes basic routing, preflight checks, LiteLLM-entry E2E, structured logs, and route-error budget gates for lightweight intent-routing validation in local or private gateway deployments.
