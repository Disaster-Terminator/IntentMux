# Cloud Hosting Notes

IntentMux can be hosted as an OpenAI-compatible route sidecar, but cloud mode
must fail closed. Do not move the whole local runtime directory as one storage
bucket.

The deployment goal is the whole gateway stack: LiteLLM, IntentMux, managed
Postgres, hosted embedding, and hosted monitoring. This repository owns only
the IntentMux piece of that rollout. LiteLLM and client changes still need
their own rollout gates.

## Deployment Boundary

For the current cloud plan, Azure is used only for infrastructure rehearsal and
hosting. Do not spend the Azure credit on model or embedding inference. Keep
DigitalOcean credit reserved for model calls, not for IntentMux VPS or
container infrastructure.

For the current full-gateway plan, LiteLLM is the public authenticated API and
control plane; IntentMux should be internal or otherwise protected behind it.
Provider keys, fallback, and model pools stay in LiteLLM. Routed spend
attribution for `model=intentmux` must be measured before claiming multi-user
budget isolation; first rollout is a personal gateway if all routed usage lands
on an internal IntentMux key. Use managed database services instead of a public
`postgres:16` container. Do not self-host Prometheus in the first cloud phase;
use platform logs and hosted monitoring instead.

## Required Settings

- `ROUTER_CLOUD_MODE=true`
- `ROUTER_INBOUND_API_KEY`: required in cloud mode.
- `ROUTER_CONFIG`: points at the reviewed runtime `routes.yaml`.
- `ROUTER_LITELLM_BASE_URL`: upstream OpenAI-compatible gateway.
- `ROUTER_EMBEDDING_URL` and `ROUTER_EMBEDDING_MODEL`: embedding endpoint.
- `ROUTER_EMBEDDING_API_KEY`: required when using Cloudflare Workers AI or any
  other bearer-protected hosted embedding endpoint.
- `ROUTER_EXPOSE_TARGET_MODEL_HEADER=false`: recommended for hosted edges.
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
  --embedding-url https://api.cloudflare.com/client/v4/accounts/<account-id>/ai/v1/embeddings \
  --include-route-cache
```

The builder copies only `config/routes.yaml` and the configured route bank,
normalizes `listen_host` to `0.0.0.0`, rewrites `route_bank_path` to the bundled
route bank, and then runs the cloud runtime gate. It does not copy prompt logs,
quality reports, reviews, backups, or stdout files. `--include-route-cache`
also copies `cache/route-embeddings.json` when it exists, so cloud startup can
reuse a reviewed/prewarmed route cache instead of rebuilding it through the
hosted embedding endpoint.

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

For the full gateway rollout, expose LiteLLM as the authenticated public API and
keep the IntentMux HTTP port internal or otherwise protected. A temporary public
IntentMux staging endpoint is acceptable only for rehearsal and must be removed
before client cutover. Keep embedding services, runtime storage, provider
dashboards, and databases private.

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
| `cache/route-embeddings.json` | Optional derived cache. Rebuildable, but preferred for hosted startup/prewarm. |
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
2. Confirm platform probes use unauthenticated `/health`, not `/ready`.
3. Confirm authenticated `/ready` is true.
4. Confirm `config_source` points at runtime config, not repo defaults.
5. Confirm no `placeholder_target_models` are present.
6. Confirm `ROUTER_INBOUND_API_KEY` is configured.
7. Confirm `ROUTER_CLOUD_MODE=true`.
8. Confirm `ROUTER_EXPOSE_TARGET_MODEL_HEADER=false` unless a protected debug
   edge strips the header before public responses.
9. Confirm prompt logging is `off` or `redacted`, never `raw_local`.
10. Confirm platform logs do not receive raw prompt/review artifacts.
11. Confirm unauthenticated `/ready`, `/v1/models`, and chat requests return
   `401`, while `/health` still returns `200`.
12. Confirm Cloudflare Workers AI embeddings use the OpenAI-compatible
   `/ai/v1/embeddings` endpoint shape, not native `/ai/run/...`.
13. Confirm `scripts/check_cloud_runtime.py` passes for the runtime directory
   that will be mounted or copied into the hosted container.
14. Confirm the mounted runtime was produced by `scripts/build_cloud_runtime.py`
    or reviewed to the same allowlist: config plus route bank only.
15. Confirm the route cache is packaged or prewarmed before production traffic,
    and route-bank-missing/cache-miss/embedding-failure startup cases are
    tested.

Keep provider routing, fallback, budget, and key distribution in the upstream
gateway. IntentMux owns only intent routing and metadata audit.
