# IntentMux

> OpenAI-compatible intent router for `lite` / `deep` model tiers.
> Cost-first by default, with escalation only when there is enough evidence.

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

<table>
  <tr>
    <td><strong>Two-tier routing</strong><br>`auto` routes automatically; `lite` / `deep` are explicit model entries.</td>
    <td><strong>Clear boundary</strong><br>Keep LiteLLM responsible for provider routing, fallback, rate limits, keys, and budgets.</td>
  </tr>
  <tr>
    <td><strong>Auditable logs</strong><br>Route audit logs are metadata-only by default; private deployments can enable prompt review logs.</td>
    <td><strong>Verify first</strong><br>Use `/ready`, preflight, E2E, daily health, and Beads to check current state.</td>
  </tr>
</table>

## What It Is

IntentMux is a lightweight routing sidecar. It accepts OpenAI-compatible chat
completion requests and routes `model=auto` traffic to two product routes:

- `lite`: lower-risk, lower-cost, lightweight tasks.
- `deep`: code, debugging, architecture, risk analysis, and tasks that need a
  more capable model.

IntentMux is not a model provider and does not replace LiteLLM, OpenRouter, or
another provider gateway. It owns entry-model semantics, route decisions,
OpenAI-compatible proxying, and auditable route metadata.

```text
model=auto -> route_id(lite/deep) -> target_model -> OpenAI-compatible upstream
```

Supported topologies:

```text
Direct gateway:
client -> IntentMux :4001/v1, model=auto|lite|deep
       -> OpenAI-compatible upstream

LiteLLM-first sidecar:
client -> LiteLLM :4000, model=semantic-router
       -> IntentMux :4001
       -> LiteLLM target model group
```

If LiteLLM already manages provider routing, fallback, keys, budgets, and model
pools, keep those responsibilities in LiteLLM. IntentMux only adds intent
routing.

## Routing Standard

Default decision order:

```text
explicit route -> hard escalation -> semantic score + threshold -> fallback lite
```

- `model=lite` / `model=deep` or `metadata.route_id` is an explicit route.
- Hard rules are reserved for high-risk escalation such as security, credential
  leakage, production incidents, or data corruption.
- Generic engineering terms, tool-call structure, long context, and agent shape
  are audit signals, not direct deep-routing triggers.
- Embedding failures fail open to `fallback_route_id`, normally `lite`.
- Upstream connection failures or 5xx return redacted `502`; upstream 4xx are
  passed through and recorded as `upstream_non_200`.

The default online router uses Aurelio Semantic Router. The built-in `basic`
router is retained only as a fallback/debug baseline.

## Quick Start

Local process:

```bash
uv run python -m router.app
```

Compose example:

```bash
uv run python scripts/init_runtime_home.py
docker compose -f examples/docker-compose.yml up -d --build
```

Default endpoints:

| Service | URL |
| --- | --- |
| IntentMux | `http://127.0.0.1:4001` |
| LiteLLM upstream | `http://127.0.0.1:4000` |
| Embedding upstream | `http://127.0.0.1:1234/v1/embeddings` |

First deployment checklist:

1. Use IntentMux directly, or add a `semantic-router` model entry in LiteLLM.
2. Copy `examples/intentmux-home/` to a persistent runtime home.
3. Set `routes.lite.target_model` and `routes.deep.target_model` in runtime
   `config/routes.yaml`.
4. Check `/ready`, run preflight, and inspect one decision response.

## Configuration Contract

Core `routes.yaml` shape:

```yaml
route_model: auto
fallback_route_id: lite

routes:
  lite:
    target_model: your-lite-model
    description: low-risk lightweight tasks
    utterances:
      - explain this concept

  deep:
    target_model: your-deep-model
    description: code, debugging, architecture, risk analysis
    utterances:
      - why is this production bug intermittent
```

Production deployments should set:

- `INTENTMUX_HOME`: runtime home for config, semantic assets, logs, and cache.
- `ROUTER_CONFIG`: runtime `routes.yaml`.
- `ROUTER_LITELLM_BASE_URL`: upstream OpenAI-compatible gateway.
- `ROUTER_EMBEDDING_URL` / `ROUTER_EMBEDDING_MODEL`: embedding upstream.
- `ROUTER_AUDIT_LOG_ENABLED=true` and `ROUTER_AUDIT_LOG_DIR`: persistent route
  audit logs.
- `ROUTER_REQUIRE_ROUTE_BANK=true`: fail startup when the runtime route bank is
  missing.

`/ready` reports config source, runtime home, logging state, route-bank load
state, and route utterance counts. Do not trust docs or stale state files over
live `/ready` and current logs.

## API

Supported endpoints:

- `GET /health`
- `GET /ready`
- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/semantic-router/decision`

Entry models:

| Model | Purpose |
| --- | --- |
| `auto` | default automatic routing |
| `lite` | force the `lite` route |
| `deep` | force the `deep` route |
| `semantic-router` | LiteLLM sidecar compatibility entry, equivalent to `auto` |

`/v1/models` advertises only `auto`, `lite`, and `deep`.

Preview a route decision without forwarding upstream:

```bash
curl http://127.0.0.1:4001/v1/semantic-router/decision \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"Why is this production bug intermittent?"}]}'
```

The response includes route, target, policy, scores, thresholds, margins, and
route-bank match provenance. Matched sample text is not returned or written to
route audit logs.

## Verify First

IntentMux changes quickly. Treat docs as intent, then verify the live system.

Common checks:

```bash
uv run pytest -n auto -q
uv run ruff check .
uv run python scripts/verify_route_contract.py
uv run python scripts/preflight.py --router-base-url http://127.0.0.1:4001
curl -fsS http://127.0.0.1:4001/ready
```

Production/private deployments should also run daily health:

```bash
uv run python scripts/intentmux_daily_health.py \
  --log-dir /path/to/intentmux-home/logs \
  --timezone Asia/Shanghai \
  --min-route-records 1 \
  --run-e2e
```

Code/image changes require rebuilding and recreating the IntentMux sidecar.
Config, route-bank, or environment changes require a restart. See
[docs/production_rollout_gate.md](docs/production_rollout_gate.md).

## Logs And Quality Loop

Route audit logs are metadata-only by default: route, target, reason, status,
duration, request id, decision scores, and match provenance. They do not record
prompts, completions, token usage, or bearer tokens.

Optional prompt review logs are for private deployments only. Public deployments
should keep them disabled.

Quality changes should follow this loop:

1. Find low-confidence, failed, slow, or drifting traffic in route audit logs.
2. Use bounded replay, eval, and quality reports for before/after evidence.
3. Promote only accepted, redacted, reviewable samples into eval or route banks.
4. Ship route-bank, threshold, margin, or hard-rule changes only with a report.

Useful docs:

- [docs/PROJECT_CONTROL.md](docs/PROJECT_CONTROL.md): current control surface.
- [docs/PATROL_HANDOFF.md](docs/PATROL_HANDOFF.md): runtime patrol handoff.
- [docs/log_driven_quality_loop.md](docs/log_driven_quality_loop.md): log-driven quality loop.
- [docs/router_data_pipeline_research.md](docs/router_data_pipeline_research.md): semantic asset pipeline.
- [docs/production_rollout_gate.md](docs/production_rollout_gate.md): production rollout gate.

## Current State

IntentMux has working two-tier routing, LiteLLM sidecar compatibility,
metadata-only audit logs, route-bank provenance, preflight, E2E, daily health,
and quality-report scripts.

Infrastructure hardening still in progress:

- bounded historical replay;
- bounded health/eval output and runtime artifact retention;
- accepted-finding import gates for redacted regression cases;
- cleaner route/eval/calibration asset separation;
- more representative threshold and margin calibration evidence.

Use live tests, `/ready`, health reports, and current Beads tasks as the source
of truth, not README alone.
