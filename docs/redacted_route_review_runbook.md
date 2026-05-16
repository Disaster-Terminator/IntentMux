# Redacted Route Quality Review Runbook

Use this runbook to evaluate route quality without exposing raw prompts or private logs.

## 1) Collect redacted samples only

Create a JSONL file from review findings where every line is a **synthetic or redacted** sample:

- MUST set `redacted: true`
- MUST include non-empty `text`
- MUST include non-empty `expect` as a **route_id** (for example `fast`, `strong`)
- MUST NOT use `target_model` names in `expect` (for example `deep-upstream` is invalid)

Optional fields:

- `source` (added to output as `production_review:<source>`)
- `note` (operator hint)

## 2) Import with route config validation

Convert JSONL into eval-case YAML and validate expected routes against config:

```bash
uv run python scripts/import_review_samples.py \
  --input tests/samples/redacted_review_samples.synthetic.jsonl \
  --output /tmp/redacted_review_cases.yaml \
  --routes config/routes.yaml
```

If a sample is not redacted or `expect` is not a configured route_id, import fails.

## 3) Run review against the decision endpoint

```bash
uv run python scripts/review_decisions.py \
  --endpoint http://127.0.0.1:4001/v1/semantic-router/decision \
  --cases /tmp/redacted_review_cases.yaml \
  --routes config/routes.yaml
```

Use `--output json` for machine-readable audit output.

## 4) Interpret PASS/FAIL safely

- `PASS`: selected `route_id` equals expected `route_id`
- `FAIL`: selected `route_id` differs from expected `route_id`
- `ERROR`: decision endpoint failure (network/HTTP/request)

For audits, store the result table or JSON output, plus the redacted input file and route config revision. Do not attach raw prompts or private logs.
