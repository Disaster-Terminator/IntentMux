# IntentMux

> Lightweight, auditable intent-routing sidecar for LiteLLM.<br>
> Select a `route_id` from request intent, then resolve it to your local LiteLLM model group.

[中文](README.md)

| Area | Value |
| --- | --- |
| Purpose | Lightweight intent routing in front of LiteLLM / OpenAI-compatible gateways |
| Integration | Keep clients on LiteLLM; opt in with `model=semantic-router` |
| Entry model | `semantic-router` is the compatibility entry name; IntentMux is the product name |
| Decision shape | `route_id -> target_model`, for example `strong -> pro-router` |
| Auditability | Structured `route_complete` / `route_error` logs without prompts or bearer tokens |
| Status | Local production validation; not packaged as a public release yet |

IntentMux is not a model provider and does not replace LiteLLM. It is a
local-first routing sidecar that rewrites only selected request `model` fields:
`model=semantic-router` becomes a configured `route_id`, then resolves to a
deployment-specific `target_model`. All other model names pass through.

The default sample config uses product-level route ids such as `fast`, `strong`,
and `experimental`, mapped to local LiteLLM model groups such as `cheap-router`,
`pro-router`, and `free-probe-router`.

## Quick Start

```bash
uv run python -m router.app
```

Default endpoints:

- IntentMux sidecar: `http://127.0.0.1:4001`
- LiteLLM upstream: `http://127.0.0.1:4000`
- Embedding upstream: `http://127.0.0.1:1234/v1/embeddings`

## LiteLLM Entry

The low-intrusion path is to keep clients on LiteLLM `:4000` and change only the
model name to `semantic-router`.

```text
client -> LiteLLM :4000, model=semantic-router
       -> IntentMux :4001
       -> route_id
       -> target_model
       -> LiteLLM model group
```

`semantic-router` is the compatibility entry name. It does not have to match the
product name. LiteLLM's native `smart-router` should remain separate.

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

Structured logs count `route_id`, `target_model`, `policy_id`, `reason`,
`stream`, and `upstream_status`, while avoiding prompt and bearer-token logging.

## Decision Preview

```bash
curl http://127.0.0.1:4001/v1/semantic-router/decision \
  -H "Content-Type: application/json" \
  -d '{"model":"semantic-router","messages":[{"role":"user","content":"Why is this production bug intermittent?"}]}'
```

This returns the selected `route_id`, resolved `target_model`, `policy_id`,
reason, rewrite flag, and scores without forwarding to LiteLLM.

## Status

IntentMux is built for a real local deployment and already includes routing,
preflight, LiteLLM-entry E2E, structured logs, and route-error budget gates. It
is still in production validation and documentation polish; public-release
packaging, license polish, local-path cleanup, and release metadata should be
handled after the operational baseline is stable.
