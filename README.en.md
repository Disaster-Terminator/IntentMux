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

The default sample config uses product-level route ids such as `fast`, `strong`, and `experimental`, mapped to local LiteLLM model groups such as `cheap-router`, `pro-router`, and `free-probe-router`. These `target_model` values are deployment names, not product API names.

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

## LiteLLM Entry

The low-intrusion path is to keep clients on LiteLLM `:4000` and change only the model name to `semantic-router`.

```text
client -> LiteLLM :4000, model=semantic-router
       -> IntentMux :4001
       -> route_id
       -> target_model
       -> LiteLLM model group
```

`semantic-router` is the compatibility entry name. It does not have to match the product name. LiteLLM's native `smart-router` should remain separate.

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

docker logs --since 12h gateway_semantic_router 2>&1 \
  | uv run python scripts/check_route_error_budget.py \
      --min-total 1 \
      --max-error-rate 0 \
      --max-target-error-rate 0 \
      --max-route-error-rate 0 \
      --max-reason-rate embedding_error=0 \
      --max-upstream-status-rate 400=0
```

Structured logs count `route_id`, `target_model`, `policy_id`, `reason`, `request_id`, `request_id_source`, `stream`, and `upstream_status`, while avoiding prompts, completions, token usage, and bearer tokens. `request_id` is only for cross-layer correlation and may come from headers, `metadata.semantic_router_request_id`, the `user` field, or IntentMux itself.

## Decision Preview

```bash
curl http://127.0.0.1:4001/v1/semantic-router/decision \
  -H "Content-Type: application/json" \
  -d '{"model":"semantic-router","messages":[{"role":"user","content":"Why is this production bug intermittent?"}]}'
```

This returns the selected `route_id`, resolved `target_model`, `policy_id`, reason, rewrite flag, and scores without forwarding to LiteLLM.

## Status

IntentMux is built for a real local deployment and already includes routing, preflight, LiteLLM-entry E2E, structured logs, and route-error budget gates. It is still in production validation and documentation polish; public-release packaging, license polish, local-path cleanup, and release metadata should be handled after the operational baseline is stable.
