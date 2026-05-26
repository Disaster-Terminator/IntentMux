# Cloud Hosting Notes

IntentMux can be hosted as its own OpenAI-compatible gateway, but cloud mode
must fail closed. Do not move the whole local runtime directory as one storage
bucket.

This runbook covers IntentMux only. Keep LiteLLM, Hermes, OpenCode, and other
gateway services out of scope for this hardening pass.

## Deployment Boundary

For the current cloud plan, Azure is used only for infrastructure rehearsal and
hosting. Do not spend the Azure credit on model or embedding inference. Keep
DigitalOcean credit reserved for model calls, not for IntentMux VPS or
container infrastructure.

Expose only IntentMux as the public OpenAI-compatible API. Keep LiteLLM
protected as the upstream provider gateway for keys, fallback, budgets, and
model pools. Use managed database services instead of a public `postgres:16`
container. Do not self-host Prometheus in the first cloud phase; use platform
logs and hosted monitoring instead.

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
Build a sanitized runtime bundle from the reviewed local runtime:

```bash
uv run python scripts/build_cloud_runtime.py \
  --source-runtime /path/to/local-intentmux-runtime \
  --output-runtime /path/to/cloud-intentmux-runtime \
  --litellm-base-url https://litellm.internal \
  --embedding-url https://embedding.internal/v1/embeddings
```

The builder copies only `config/routes.yaml` and the configured route bank,
normalizes `listen_host` to `0.0.0.0`, rewrites `route_bank_path` to the bundled
route bank, and then runs the cloud runtime gate. It does not copy prompt logs,
quality reports, reviews, backups, stdout files, or caches.

Before mounting any runtime directory, run:

```bash
uv run python scripts/check_cloud_runtime.py /path/to/intentmux-home
```

Port precedence is:

```text
ROUTER_PORT -> CONTAINER_APP_PORT -> PORT -> routes.yaml/default
```

Leave `ROUTER_PORT` unset when the hosting platform injects `PORT` or
`CONTAINER_APP_PORT`.

## Public Surface

Expose only the IntentMux HTTP port. Keep upstream LiteLLM, embedding services,
runtime storage, and provider dashboards private.

`GET /health` remains unauthenticated so managed platforms can probe the
container. In cloud mode, `GET /ready` requires the same bearer token as
`/v1/chat/completions`; it includes runtime diagnostics and should not be a
public status page. The OpenAI-compatible `/v1/models` endpoint is also
protected whenever `ROUTER_INBOUND_API_KEY` or rotated inbound keys are
configured.

Run preflight with the inbound key:

```bash
uv run python scripts/preflight.py \
  --router-base-url https://your-intentmux-host \
  --intentmux-api-key "$ROUTER_INBOUND_API_KEY"
```

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

## Hosted Development Audit

Treat hosted logs as operations evidence, not as a prompt corpus.

- Use route-audit stdout and `/ready` snapshots for normal development triage.
- Export only redacted route summaries, health reports, and request ids into
  issue trackers or support bundles.
- Keep raw prompt review logs local-only; do not backfill them from cloud
  traffic unless a separate private sink, retention window, and deletion path
  have been reviewed.
- When debugging a bad route, correlate by request id first, then reproduce
  with a manually redacted prompt in a private environment.
- Rotate `ROUTER_INBOUND_API_KEY` and upstream keys through the platform secret
  manager; do not store old keys in runtime config snapshots.

## Rollout Gate

Before exposing a hosted IntentMux endpoint:

1. Run the test suite and route contract checks.
2. Confirm `/ready` is true.
3. Confirm `config_source` points at runtime config, not repo defaults.
4. Confirm no `placeholder_target_models` are present.
5. Confirm `ROUTER_INBOUND_API_KEY` is configured.
6. Confirm prompt logging is `off` or `redacted`, never `raw_local`.
7. Confirm platform logs do not receive raw prompt/review artifacts.
8. Confirm unauthenticated `/ready`, `/v1/models`, and chat requests return
   `401`, while `/health` still returns `200`.
9. Confirm `scripts/check_cloud_runtime.py` passes for the runtime directory
   that will be mounted or copied into the hosted container.
10. Confirm the mounted runtime was produced by `scripts/build_cloud_runtime.py`
    or reviewed to the same allowlist: config plus route bank only.

Keep provider routing, fallback, budget, and key distribution in the upstream
gateway. IntentMux owns only intent routing and metadata audit.
