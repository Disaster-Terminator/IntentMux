# Production Rollout Gate

IntentMux production changes must separate repository work from live container
changes. Repository commits can be built and tested freely. The production
container is changed only after this gate passes.

## Change Classes

Config or asset changes:

- `/data/config/routes.yaml`
- `/data/semantic_sets/route_bank.yaml`
- environment variables such as `ROUTER_LITELLM_BASE_URL`

These require an IntentMux sidecar restart because routes and vectors are loaded
at startup. They do not require an image rebuild.

Code or image changes:

- `router/`
- `scripts/`
- `Dockerfile`
- built-in `config/`
- `examples/`

These require image rebuild and container replacement. Do not apply them to the
production container during exploratory work.

## Read-Only Checks

These checks are safe during investigation:

```bash
docker ps --format '{{.Names}}\t{{.Status}}\t{{.Ports}}'
docker logs --since 30m intentmux
curl -sS http://127.0.0.1:4001/health
curl -sS http://127.0.0.1:4001/ready
uv run python scripts/intentmux_daily_health.py \
  --repo /path/to/IntentMux \
  --log-dir /path/to/intentmux-home/logs
```

Avoid `docker restart`, `docker compose up`, `docker compose build`, and
`docker exec` during read-only review.

## Pre-Rollout Gate

Run from the repository before touching production:

```bash
uv run python -m pytest -q
uv run python scripts/verify_route_contract.py
uv run python scripts/eval_routes.py --mock-embeddings > /tmp/intentmux-eval.txt
uv run python scripts/router_log_summary.py /path/to/intentmux-home/logs/routes/*.jsonl --json > /tmp/intentmux-routes.json
uv run python scripts/route_quality_report.py \
  --eval-output /tmp/intentmux-eval.txt \
  --route-summary-json /tmp/intentmux-routes.json \
  --route-bank examples/route_bank.sample.yaml \
  --json-output /tmp/intentmux-quality.json \
  --markdown-output /tmp/intentmux-quality.md
```

For the local production stack, run:

```bash
set -a; . /path/to/litellm.env; set +a
uv run python scripts/preflight.py --router-base-url http://127.0.0.1:4001
uv run python scripts/intentmux_daily_health.py \
  --repo /path/to/IntentMux \
  --log-dir /path/to/intentmux-home/logs \
  --litellm-env /path/to/litellm.env \
  --run-e2e
```

The gate passes only when:

- unit tests pass;
- route contract verification passes;
- route evals pass;
- route-bank, threshold, margin, or hard-rule changes include a fresh quality
  report;
- `/ready` is true;
- strict E2E passes;
- latest health report has `not_ok=0` for today's logs;
- any route-bank change has source attribution and no raw production prompt.
- production-log-driven changes use only human-reviewed, redacted review
  samples.

## Rollout

For config or route-bank changes:

1. Back up the current mounted IntentMux home.
2. Copy the reviewed config or route bank into `/data`.
3. Restart only the IntentMux sidecar.
4. Run `/ready`, preflight, and strict daily health with E2E.
5. Watch the next health report for route distribution drift and
   `embedding_error`.

For code/image changes:

1. Build the image outside production first.
2. Run unit tests and local E2E against the built image.
3. Recreate only the IntentMux sidecar.
4. Run the same post-rollout checks.

## Rollback

Rollback keeps LiteLLM untouched whenever possible:

1. Restore the previous mounted IntentMux config or route bank.
2. Restart only the IntentMux sidecar.
3. Verify `/ready`.
4. Run `scripts/intentmux_daily_health.py --run-e2e` with the production log
   directory and LiteLLM env file.
5. Confirm route logs are still writing to the mounted audit directory.

If code rollout fails, redeploy the previous pushed image or commit and run the
same checks. Do not edit LiteLLM config unless the failure is proven to be in the
LiteLLM entry model.
