# IntentMux

> Lightweight local AI gateway for routing OpenAI-compatible requests between `lite` and `deep` model tiers.<br>
> Preserves LiteLLM sidecar compatibility without owning provider routing, keys, budgets, or fallback.

<p align="center">
  <img alt="runtime Python 3.11+" src="https://img.shields.io/badge/runtime-Python%203.11%2B-3776AB">
  <img alt="entries auto lite deep" src="https://img.shields.io/badge/entries-auto%20%7C%20lite%20%7C%20deep-0EA5E9">
  <img alt="LiteLLM sidecar compatible" src="https://img.shields.io/badge/LiteLLM-sidecar%20compatible-16A34A">
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

IntentMux is a lightweight local AI gateway that routes OpenAI-compatible requests between `lite` and `deep` model tiers with auditable decisions, while preserving LiteLLM sidecar compatibility.

<table>
  <tr>
    <td><strong>Two-tier routing</strong><br>`auto` routes automatically; `lite` / `deep` are explicit model entries.</td>
    <td><strong>Clear boundary</strong><br>Keep LiteLLM responsible for provider routing, fallback, rate limits, keys, and budgets.</td>
  </tr>
  <tr>
    <td><strong>Auditable logs</strong><br>Route audit logs are metadata-only by default; private local deployments can explicitly enable prompt review logs.</td>
    <td><strong>Operational gates</strong><br>Ship with preflight, LiteLLM-entry E2E, log summaries, and route-error budget checks.</td>
  </tr>
</table>

## Project Boundary

IntentMux is not a model provider and does not replace LiteLLM. It owns OpenAI-compatible gateway protocol, entry-model semantics, routing decisions, and audit logs. LiteLLM remains the recommended upstream for provider routing, provider fallback, provider credentials, virtual keys, budgets, and model pools.

```text
model=auto -> route_id(lite/deep) -> target_model -> OpenAI-compatible upstream
```

Canonical entry models:

- `auto`: default automatic routing entry.
- `lite`: explicit lightweight, lower-cost, lower-risk tier.
- `deep`: explicit deeper-reasoning, higher-capability tier.

| Requested model | Meaning | Behavior |
| --- | --- | --- |
| `auto` | Preferred routed entry | Runs IntentMux routing |
| `semantic-router` | Legacy LiteLLM sidecar entry | Same as `auto`; retained for compatibility |
| `lite` | Explicit lightweight tier | Routes to configured `lite.target_model` |
| `deep` | Explicit high-capability tier | Routes to configured `deep.target_model` |

Compatibility entries and aliases:

- `semantic-router`: legacy LiteLLM sidecar entry alias. It remains accepted, but is no longer the preferred advertised entry.
- `fast`: legacy route alias for `lite`.
- `strong`: legacy route alias for `deep`.

`/v1/models` advertises only `auto`, `lite`, and `deep`. It does not advertise `semantic-router` or leak local LiteLLM model-group names. `target_model` values are deployment configuration, not product API names.

IntentMux can still run as a LiteLLM sidecar. Keep provider secrets, tokens, `.env` files, and mounted LiteLLM data outside this repository.

Current compatibility scope:

- Supports `/health`, `/ready`, `/v1/models`, `/v1/chat/completions`, and `/v1/semantic-router/decision`.
- Supports streaming and non-streaming chat completion pass-through.
- Does not claim full OpenAI API compatibility and does not implement `/v1/responses`.
- Does not manage provider pools; use LiteLLM or another OpenAI-compatible upstream for provider routing, keys, budgets, and fallback.
- Keeps inbound IntentMux auth, upstream auth, and embedding auth as separate secrets.
- Treats embedding degradation as route fallback; upstream transport or status failures return controlled, redacted gateway errors.

The default router borrows the common strong/weak LLM-router shape and Semantic
Router thresholding:

```text
explicit override -> high-precision hard escalation -> agent structure signal -> semantic score + threshold -> fallback lite
```

`hard_rules` are reserved for high-risk escalation signals such as security,
secret leakage, production incidents, rollbacks, or data corruption. Ambiguous
engineering words such as `PR`, `debug`, deployment, indexing, exceptions, and
errors are handled by semantic examples and thresholds by default, so agent
context accumulation does not permanently pin a conversation to `deep`.

OpenAI-compatible requests with `tools` / legacy `functions`, tool-call history,
`tool_choice`, or long multi-turn context are escalated to `deep` with
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

Tracked examples use generic paths and generic model names. Local runtime logs,
prompt review logs, generated route banks, production compose overrides, and
site-specific rollout wrappers remain outside git. Public deployment
instructions should not hardcode workstation paths; keep those in local
environment variables or untracked wrapper scripts.

## Entry Models

The new default path is to use IntentMux directly as an OpenAI-compatible `base_url` and request the canonical entry models:

```text
client -> IntentMux :4001/v1, model=auto|lite|deep
       -> route_id(lite/deep)
       -> target_model
       -> OpenAI-compatible upstream
```

- `model=auto`: run normal routing.
- `model=lite` / `model=deep`: force the corresponding route id and skip semantic routing.
- `/v1/models`: list only `auto`, `lite`, and `deep`.

The LiteLLM sidecar compatibility path remains supported. Clients can keep using LiteLLM `:4000` and change only the model name to the legacy entry `semantic-router`.

```text
client -> LiteLLM :4000, model=semantic-router
       -> IntentMux :4001
       -> route_id
       -> target_model
       -> LiteLLM model group
```

Configure `semantic-router` in LiteLLM as a model entry that points to the IntentMux sidecar. Requests that use that legacy model name run automatic routing. `semantic-router` is a compatibility alias and is not listed by IntentMux `/v1/models`. Legacy route ids `fast` and `strong` remain aliases for `lite` and `deep`.

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

Local production can keep using the LiteLLM sidecar entry so clients do not
bypass existing LiteLLM provider routing, fallback, keys, and budgets. Development
and CI should still cover both direct gateway mode and sidecar mode:

| Scenario | Entry | Primary checks |
| --- | --- | --- |
| Local production | LiteLLM `:4000`, `model=semantic-router` | `e2e_litellm_entry.py` and rollout-helper legacy preflight |
| Direct gateway | IntentMux `:4001/v1`, `model=auto|lite|deep` | `preflight.py --model auto`, `/v1/models`, and protocol tests |
| Sidecar compatibility | LiteLLM model entry -> IntentMux | `tests/test_e2e_litellm_entry.py` |
| Protocol regression | IntentMux -> OpenAI-compatible upstream | `tests/test_protocol_gateway.py` |

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

Structured route audit logs count `route_id`, `target_model`, `policy_id`, `reason`, `request_id`, `request_id_source`, `stream`, `upstream_status`, `ok`, `outcome`, `decision_ms`, and `upstream_ms`, while avoiding prompts, completions, token usage, and bearer tokens. Streaming requests also include `upstream_headers_ms` and `upstream_body_ms`. `event` is lifecycle; `ok/outcome` is route health. Upstream non-2xx responses record `ok=false` and `outcome=upstream_non_200`. `embedding_error` has a dedicated budget shortcut because it can fail open to the configured fallback route, whose default product meaning is `lite`, without making the user request fail.

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
  -d '{"model":"auto","messages":[{"role":"user","content":"Why is this production bug intermittent?"}]}'
```

If `ROUTER_INBOUND_API_KEY` is enabled, include the inbound auth header:

```bash
curl http://127.0.0.1:4001/v1/semantic-router/decision \
  -H "Authorization: Bearer $ROUTER_INBOUND_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"Why is this production bug intermittent?"}]}'
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
security analysis should usually send `model=deep` or `metadata.route_id=deep` explicitly
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
