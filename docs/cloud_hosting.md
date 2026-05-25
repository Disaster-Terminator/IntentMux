# Cloud Hosting Notes

IntentMux can be hosted as its own OpenAI-compatible gateway, but cloud mode
must fail closed. Do not move the whole local runtime directory as one storage
bucket.

This runbook covers IntentMux only. Keep LiteLLM, Hermes, OpenCode, and other
gateway services out of scope for this hardening pass.

## Required Settings

- `ROUTER_CLOUD_MODE=true`
- `ROUTER_INBOUND_API_KEY`: required in cloud mode.
- `ROUTER_CONFIG`: points at the reviewed runtime `routes.yaml`.
- `ROUTER_LITELLM_BASE_URL`: upstream OpenAI-compatible gateway.
- `ROUTER_EMBEDDING_URL` and `ROUTER_EMBEDDING_MODEL`: embedding endpoint.
- `ROUTER_REQUIRE_ROUTE_BANK=true`: recommended once the runtime route bank is
  mounted.

Keep API keys in the platform secret manager or environment variables. Do not
put provider keys, bearer tokens, or local-only endpoints in tracked config.
Replace workstation-only hosts such as `host.docker.internal` before rollout.

Port precedence is:

```text
ROUTER_PORT -> CONTAINER_APP_PORT -> PORT -> routes.yaml/default
```

Leave `ROUTER_PORT` unset when the hosting platform injects `PORT` or
`CONTAINER_APP_PORT`.

## Runtime Artifacts

| Artifact | Cloud handling |
| --- | --- |
| `config/routes.yaml` | Mount or inject as reviewed config. No placeholders or secrets. |
| `semantic_sets/*.yaml` | Mount reviewed route/eval/calibration assets. |
| `cache/route-embeddings.json` | Optional derived cache. Rebuildable. |
| `logs/routes/*.jsonl` | Metadata-only route audit. Prefer stdout in hosted mode. |
| `logs/prompts/*.jsonl` | Private local data. Do not ship raw. |
| `reviews/*` and `reports/*` | Treat as private unless manually redacted. |
| `logs/quality/*` | Mixed reports; review before exporting. |
| backups and temp configs | Do not mount into hosted runtime by default. |

Cloud mode rejects `ROUTER_PROMPT_LOG_MODE=raw_local`. Use `off` by default.
Use `redacted` only with an explicit private log sink and retention policy.

## Route Audit

Route audit records are metadata-only and are always emitted through the
`intentmux` logger when requests complete or fail. For managed platforms, enable
audit logging with stdout-only mode by leaving `ROUTER_AUDIT_LOG_DIR` empty:

```bash
ROUTER_AUDIT_LOG_ENABLED=true
ROUTER_AUDIT_LOG_DIR=
```

Set `ROUTER_AUDIT_LOG_DIR` only when a private writable volume is intentional.

## Rollout Gate

Before exposing a hosted IntentMux endpoint:

1. Run the test suite and route contract checks.
2. Confirm `/ready` is true.
3. Confirm `config_source` points at runtime config, not repo defaults.
4. Confirm no `placeholder_target_models` are present.
5. Confirm `ROUTER_INBOUND_API_KEY` is configured.
6. Confirm prompt logging is `off` or `redacted`, never `raw_local`.
7. Confirm platform logs do not receive raw prompt/review artifacts.

Keep provider routing, fallback, budget, and key distribution in the upstream
gateway. IntentMux owns only intent routing and metadata audit.
