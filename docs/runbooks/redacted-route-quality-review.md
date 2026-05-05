# Redacted route quality review runbook

Use this workflow to review route decisions without exposing raw prompts or private logs.

## 1) Collect only redacted samples

- Input must be JSONL, one object per line.
- Keep only redacted text snippets suitable for internal sharing.
- Every line must include `"redacted": true`.
- Do **not** include raw conversation logs, credentials, tokens, or user identifiers.

## 2) Required JSONL fields

Each sample line must include:

- `text` (string): redacted prompt text
- `expect` (string): expected **route_id**
- `redacted` (boolean): must be `true`

Optional fields:

- `source` (string)
- `note` (string)

Example:

```json
{"text":"[REDACTED] payment flow timed out in prod","expect":"strong","redacted":true,"source":"incident_review"}
```

> `expect` must be a configured `route_id` (for example `fast`, `strong`), **not** a deployment `target_model` name.

## 3) Import with route-config validation

Convert JSONL to eval YAML and validate expected routes against your active route config:

```bash
uv run python scripts/import_review_samples.py \
  --input tests/samples/redacted_review_fixture.jsonl \
  --output /tmp/redacted_review_cases.yaml \
  --routes config/routes.yaml
```

If a sample uses a `target_model` in `expect`, import fails with a route-id validation error.

## 4) Run `review_decisions` against the decision endpoint

Point the review script at the sidecar decision endpoint:

```bash
uv run python scripts/review_decisions.py \
  --cases /tmp/redacted_review_cases.yaml \
  --endpoint http://127.0.0.1:8080/v1/route/decision \
  --routes config/routes.yaml
```

## 5) Interpret PASS/FAIL safely

- `PASS`: returned `route_id` matches expected `route_id`.
- `FAIL`: returned `route_id` differs from expected `route_id`.
- Use route-level aggregates and mismatch counts for audits.
- Do not copy raw prompts into tickets; reference sample IDs/notes instead.
