# IntentMux

> Lightweight, auditable intent-routing sidecar for LiteLLM.<br>
> Select a `route_id` from request intent, then resolve it to your local LiteLLM model group.

<p align="center">
  <img alt="runtime Python 3.11+" src="https://img.shields.io/badge/runtime-Python%203.11%2B-3776AB">
  <img alt="entry semantic-router" src="https://img.shields.io/badge/entry-semantic--router-0EA5E9">
  <img alt="gateway LiteLLM compatible" src="https://img.shields.io/badge/gateway-LiteLLM%20compatible-16A34A">
  <img alt="logs no prompt or token" src="https://img.shields.io/badge/logs-no%20prompt%20%7C%20token-7C3AED">
</p>
<p align="center">
  <img alt="built with FastAPI" src="https://img.shields.io/badge/built%20with-FastAPI-009688">
  <img alt="config YAML" src="https://img.shields.io/badge/config-YAML-CB171E">
  <img alt="tests pytest" src="https://img.shields.io/badge/tests-pytest-0A9EDC">
  <img alt="package uv" src="https://img.shields.io/badge/package-uv-DE5FE9">
</p>

[中文](README.md)

## One Line

IntentMux is a local-first OpenAI-compatible / LiteLLM-compatible routing sidecar. Clients keep using the existing LiteLLM endpoint and opt in with `model=semantic-router`; IntentMux selects a `route_id` from request intent, then resolves that route to the deployment-specific `target_model`.

<table>
  <tr>
    <td><strong>Intent routing</strong><br>Select product-level routes such as `fast`, `strong`, and `experimental` from request content.</td>
    <td><strong>Low-intrusion integration</strong><br>Keep LiteLLM responsible for providers, fallback, rate limits, and authentication.</td>
  </tr>
  <tr>
    <td><strong>Auditable logs</strong><br>Record structured `route_complete` / `route_error` events without prompts, tokens, or bearer tokens.</td>
    <td><strong>Operational gates</strong><br>Ship with preflight, LiteLLM-entry E2E, log summaries, and route-error budget checks.</td>
  </tr>
</table>

## Project Boundary

IntentMux is not a model provider and does not replace LiteLLM. It only handles the configured compatibility entry model:

```text
model=semantic-router -> route_id -> target_model -> LiteLLM model group
```

All other model names pass through.

The default sample config uses product-level route ids such as `fast`, `strong`, and `experimental`, mapped to LiteLLM model groups such as `cheap-router`, `pro-router`, and `free-probe-router`. These `target_model` values are deployment names, not product API names.

Deploy IntentMux as a sidecar next to LiteLLM and keep provider secrets, tokens, `.env` files, and mounted LiteLLM data outside this repository.

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

For container deployment, run IntentMux as a LiteLLM sidecar with its own mounted home:

```text
litellm/
  docker-compose.yml
  config.yaml
  .env
  intentmux/
    config/routes.yaml
    semantic_sets/route_bank.yaml
    logs/routes/YYYY-MM-DD.jsonl
```

Inside the container, `/app` is image code and `/data` is the user-mounted IntentMux home:

```yaml
services:
  intentmux:
    image: ghcr.io/<owner>/intentmux:<version>
    volumes:
      - ./intentmux:/data
    environment:
      ROUTER_CONFIG: /data/config/routes.yaml
      ROUTER_AUDIT_LOG_ENABLED: "true"
      ROUTER_AUDIT_LOG_DIR: /data/logs/routes
      ROUTER_LITELLM_BASE_URL: http://litellm:4000
```

`examples/intentmux-home/` is a copyable runtime template. Keep LiteLLM `.env`, provider tokens, databases, and raw prompts outside the IntentMux home.

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
```

LiteLLM-entry E2E:

```bash
uv run python scripts/e2e_litellm_entry.py --litellm-base-url http://127.0.0.1:4000
```

## Log Review

```bash
docker logs --since 12h gateway_semantic_router 2>&1 \
  | uv run python scripts/router_log_summary.py

uv run python scripts/router_log_summary.py /data/logs/routes/*.jsonl

docker logs --since 12h gateway_semantic_router 2>&1 \
  | uv run python scripts/check_route_error_budget.py \
      --min-total 1 \
      --max-error-rate 0 \
      --max-target-error-rate 0 \
      --max-route-error-rate 0 \
      --max-not-ok-rate 0 \
      --max-reason-rate embedding_error=0 \
      --max-upstream-status-rate 400=0
```

Structured logs count `route_id`, `target_model`, `policy_id`, `reason`, `request_id`, `request_id_source`, `stream`, `upstream_status`, `ok`, and `outcome`, while avoiding prompts, completions, token usage, and bearer tokens. `event` is lifecycle; `ok/outcome` is route health. Upstream non-2xx responses record `ok=false` and `outcome=upstream_non_200`.

## Decision Preview

```bash
curl http://127.0.0.1:4001/v1/semantic-router/decision \
  -H "Content-Type: application/json" \
  -d '{"model":"semantic-router","messages":[{"role":"user","content":"Why is this production bug intermittent?"}]}'
```

This returns the selected `route_id`, resolved `target_model`, `policy_id`, reason, rewrite flag, and scores without forwarding to LiteLLM.

## Runtime Behavior

Run IntentMux as a sidecar in the same deployment boundary as LiteLLM.

- Docker health uses `/health` to avoid readiness flapping restart loops.
- `/ready` checks router, LiteLLM, and embedding availability.
- When embeddings are unavailable, chat requests fail open to `fallback_route_id` and log `reason=embedding_error`.
- LiteLLM/upstream `5xx` responses or connection errors fail closed as redacted `502` responses and log `route_error`.
- LiteLLM/upstream `4xx` responses are passed through by proxy semantics, but audit logs mark them as `ok=false` / `outcome=upstream_non_200`.

## Current Capabilities

IntentMux includes basic routing, preflight checks, LiteLLM-entry E2E, structured logs, and route-error budget gates for lightweight intent-routing validation in local or private gateway deployments.
