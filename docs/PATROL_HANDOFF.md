# IntentMux Patrol Handoff

This is the repository-safe handoff for running IntentMux patrol checks.
Deployment-specific paths, secrets, cron schedules, and notification targets
belong outside this repository.

## Responsibility Boundary

IntentMux provides:

- route-log summary scripts;
- route error-budget gates;
- LiteLLM-entry E2E checks;
- preflight checks;
- structured audit logs without prompt, completion, token, or bearer-token
  content.

An external scheduler such as cron, systemd timers, CI, or a private ops agent
provides:

- scheduling;
- stdout and exit-code collection;
- report delivery;
- retry and alert policy.

Repository scripts are the reusable product surface. Scheduler wrappers, job
IDs, notification targets, and machine-specific absolute paths are deployment
state and should stay outside this repository.

## Runtime Inputs

Choose these values in your deployment:

```text
INTENTMUX_REPO=/path/to/IntentMux
INTENTMUX_HOME=/path/to/intentmux-home
INTENTMUX_LOG_DIR=/path/to/intentmux-home/logs
INTENTMUX_ROUTER_BASE_URL=http://127.0.0.1:4001
INTENTMUX_LITELLM_BASE_URL=http://127.0.0.1:4000
INTENTMUX_LITELLM_ENV=/path/to/litellm.env
INTENTMUX_LOG_CONTAINER=intentmux
INTENTMUX_MIN_ROUTE_RECORDS=0
INTENTMUX_TIMEZONE=Asia/Shanghai
```

`INTENTMUX_HOME` is the runtime root for user-owned config, semantic assets,
logs, health reports, and local review artifacts. `INTENTMUX_LOG_DIR` may be
omitted by wrappers that export `INTENTMUX_HOME`; the daily health script then
defaults to `$INTENTMUX_HOME/logs`. If neither variable is set, repository-local
manual runs use the ignored `.intentmux-home/logs` directory. Production
schedulers should set `INTENTMUX_HOME` or `INTENTMUX_LOG_DIR` explicitly.

`INTENTMUX_LOG_DIR` is the directory that contains:

```text
routes/YYYY-MM-DD.jsonl
health/intentmux-health-YYYY-MM-DD.json
health/intentmux-health-YYYY-MM-DD.md
health/intentmux-health-latest.json
health/intentmux-health-latest.md
```

The LiteLLM env file is optional. Use it only when E2E needs to source
`LITELLM_MASTER_KEY` or equivalent credentials.

## Main Patrol Command

```bash
uv --directory "$INTENTMUX_REPO" run python scripts/intentmux_daily_health.py \
  --repo "$INTENTMUX_REPO" \
  --log-dir "$INTENTMUX_LOG_DIR" \
  --router-base-url "$INTENTMUX_ROUTER_BASE_URL" \
  --litellm-base-url "$INTENTMUX_LITELLM_BASE_URL" \
  --timezone "$INTENTMUX_TIMEZONE" \
  --min-route-records "$INTENTMUX_MIN_ROUTE_RECORDS" \
  --log-container "$INTENTMUX_LOG_CONTAINER"
```

By default this does not send real chat requests. It writes daily JSON and
Markdown reports under `$INTENTMUX_LOG_DIR/health/`.
Set `INTENTMUX_MIN_ROUTE_RECORDS` to a positive integer when the patrol should
distinguish "healthy with traffic" from "no evidence yet".

For low-frequency deep checks or post-change validation, add strict E2E:

```bash
uv --directory "$INTENTMUX_REPO" run python scripts/intentmux_daily_health.py \
  --repo "$INTENTMUX_REPO" \
  --log-dir "$INTENTMUX_LOG_DIR" \
  --router-base-url "$INTENTMUX_ROUTER_BASE_URL" \
  --litellm-base-url "$INTENTMUX_LITELLM_BASE_URL" \
  --litellm-env "$INTENTMUX_LITELLM_ENV" \
  --timezone "$INTENTMUX_TIMEZONE" \
  --min-route-records "$INTENTMUX_MIN_ROUTE_RECORDS" \
  --log-container "$INTENTMUX_LOG_CONTAINER" \
  --run-e2e
```

## Report Contract

The daily health report includes:

- `ready`
- `route_summary_today`
- `route_summary_all_logs`
- `traffic_evidence`
- `log_consistency`
- `quality_artifacts`
- `strict_budget`
- `tolerant_budget`
- `e2e`
- `paths`

`route_summary_today` is the main daily signal. `traffic_evidence` reports the
number of valid `route_complete` / `route_error` records in today's route log
and compares it with `--min-route-records`. Malformed JSON, missing events, and
unknown events do not count as traffic evidence. "Today" defaults to `Asia/Shanghai`, matching the
default audit-log partition timezone. Use `--date YYYY-MM-DD` for an explicit
file date. `route_summary_all_logs` is only historical context.

`log_consistency` compares today's route audit log with the optional prompt
review log for the same date. It reports duplicate `request_id` counts, missing
`request_id` counts, `route_without_prompt`, and `prompt_without_route`.
Schedulers may alert or annotate reports from these fields, but should treat
them as auditability signals rather than core service readiness: prompt review
logging is optional and can have boundary cases around stream cancellation,
process restart, or date partition edges. Recent prompt review records are
counted under `prompt_recent_in_grace` and excluded from `prompt_without_route`
for a short in-flight grace window.

`quality_artifacts` points to generic files written under
`$INTENTMUX_LOG_DIR/quality/YYYY-MM-DD/`:

- route summary JSON for the current day;
- eval JSON for `current-router`, `always-lite`, `always-deep`, and
  `hard-rule-only`;
- route quality report JSON/Markdown;
- review candidates JSON/Markdown;
- metadata-only AI review packet JSON/Markdown.

These artifacts are generated by repository scripts only. The daily health
script does not call an AI provider and does not include raw prompt text in the
default AI review packet.

Slow request rows include:

- `decision_ms`
- `upstream_ms`
- `upstream_headers_ms`
- `upstream_body_ms`

Schedulers should not parse prompt text from route audit logs because those
logs do not write prompt text. Optional prompt review logs live under the
separate `logs/prompts` tree and are for local AI review plus human audit, not
cron parsing.

## Read-Only Checks

```bash
curl -sS "$INTENTMUX_ROUTER_BASE_URL/ready"
uv --directory "$INTENTMUX_REPO" run python scripts/router_log_summary.py \
  "$INTENTMUX_LOG_DIR/routes/*.jsonl" \
  --slow-request-limit 10
```

For today's strict budget:

```bash
uv --directory "$INTENTMUX_REPO" run python scripts/check_route_error_budget.py \
  "$INTENTMUX_LOG_DIR/routes/$(date +%F).jsonl" \
  --min-total 1 \
  --max-error-rate 0 \
  --max-target-error-rate 0 \
  --max-route-error-rate 0 \
  --max-not-ok-rate 0 \
  --max-embedding-error-rate 0 \
  --max-upstream-status-rate 400=0
```

For a tolerant budget, tune thresholds from your own production baseline.

## E2E Expectations

Strict LiteLLM-entry E2E should verify:

- non-stream strong route succeeds;
- stream strong route succeeds;
- non-stream fast route succeeds;
- each probe has a matching IntentMux route log by request id;
- route audit logs do not contain prompts or bearer tokens.

## Production Change Discipline

Repository changes do not imply production container changes. Before restarting
or rebuilding a live sidecar, use [production_rollout_gate.md](production_rollout_gate.md).

After code or config changes, run at least:

```bash
uv run python -m pytest -q
uv run python scripts/verify_route_contract.py
uv run python scripts/eval_routes.py --mock-embeddings
```

Changes touching runtime route behavior or LiteLLM integration also require
preflight and strict E2E against the target stack.
