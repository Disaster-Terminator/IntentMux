# Log-Driven Quality Loop

IntentMux improves routing quality from production metadata, optional local
prompt review logs, and redacted review samples. Route audit logs identify
routing drift, low-confidence decisions, failures, and latency regressions;
prompt review logs provide local-only semantic evidence when explicitly
enabled. Only human-reviewed, redacted samples are promoted into eval cases or
route banks.

## Boundary

The route audit log is metadata only. It may contain `request_id`, `route_id`,
`target_model`, `reason`, scores, upstream status, and timing fields. It must
not contain raw prompts, completions, request bodies, token usage, bearer
credentials, provider keys, or LiteLLM secrets.

Prompt review logging is a separate local-only surface. It is disabled by
default with `ROUTER_PROMPT_LOG_MODE=off`. When enabled, it writes to
`ROUTER_PROMPT_LOG_DIR/YYYY-MM-DD.jsonl`, not to stdout, route audit JSONL, or
daily health output.

- `ROUTER_PROMPT_LOG_MODE=redacted` records latest user text after masking
  common bearer/sk/base64 credentials.
- `ROUTER_PROMPT_LOG_MODE=raw_local` records latest user text as-is for private
  local review. Do not sync, publish, or attach this directory to public
  reports.

`request_id` is an operational correlation key. It helps a human operator find
the relevant context in systems they already control, but it is not training
text and should not be copied into public route-bank sources.

## Loop

```text
audit logs
  -> daily health / route summary / route-error budget
  -> review candidate selection
  -> optional local prompt review lookup by request_id
  -> human review
  -> redacted production_review JSONL
  -> eval bank import
  -> route bank / threshold / margin change
  -> route quality report
  -> production rollout gate
  -> observe new logs
```

## Review Candidate Selection

Use `scripts/select_review_candidates.py` to select metadata-only records that
deserve human review:

```bash
uv run python scripts/select_review_candidates.py /data/logs/routes/*.jsonl \
  --routes /data/config/routes.yaml \
  --prompt-path "/data/logs/prompts/*.jsonl" \
  --json-output /tmp/intentmux-review-candidates.json \
  --markdown-output /tmp/intentmux-review-candidates.md
```

The script selects records for signals such as:

- `reason=low_confidence`;
- `reason=embedding_error`;
- route errors;
- upstream non-2xx responses;
- scores close to the route threshold;
- score margins close to the configured margin;
- slow requests above the configured duration threshold.

When prompt review logs are passed with `--prompt-path`, the script joins them
by `request_id` and only reports whether a candidate has matching local review
evidence, whether that evidence was truncated, and the prompt character count.
It does not print prompt text or infer framework identity from prompt contents.

The output is intentionally limited to route metadata and safe structural
signals:

```json
{
  "request_id": "req-...",
  "timestamp": "2026-05-13T00:00:00Z",
  "route_id": "fast",
  "target_model": "cheap-router",
  "reason": "low_confidence",
  "score": 0.53,
  "second_score": 0.51,
  "duration_ms": 1234.5,
  "upstream_status": 200,
  "format_signals": {
    "tools_present": true,
    "tool_history": false,
    "message_count": 8,
    "approx_input_chars": 12000
  },
  "prompt_review": {
    "matched": true,
    "truncated": false,
    "text_chars": 12000
  },
  "review_reasons": ["low_confidence", "near_margin"]
}
```

`format_signals` are derived from OpenAI-compatible request structure, not from
private prompt text. They are audit evidence for future routing-policy changes;
do not treat them as automatic route decisions until production logs show a
stable pattern.

## Promoting Samples

Candidate records do not become eval cases automatically. A human must review
the request in their own operational context, remove private content, rewrite
the example into a safe representative prompt, and set `redacted: true`.

Example source file:

```bash
data/source_samples/production_review.example.jsonl
```

Import reviewed samples:

```bash
uv run python scripts/import_review_samples.py \
  --input data/source_samples/production_review.redacted.jsonl \
  --output data/semantic_sets/production_review_eval_cases.yaml \
  --routes config/routes.yaml
```

Every imported sample must use a product `route_id` such as `fast` or `strong`
as `expect`; deployment-side target model names such as `cheap-router` and
`pro-router` must not be used as eval labels.

Local production review JSONL files are deployment artifacts and are ignored by
git. Keep only curated public examples such as
`data/source_samples/production_review.example.jsonl` in the repository.

## Change Gate

Any route bank, threshold, margin, or hard-rule change should include:

- route eval output;
- route log summary from recent production traffic;
- `scripts/route_quality_report.py` JSON/Markdown output;
- candidate review evidence when the change is production-log driven;
- rollback plan limited to IntentMux config, assets, or image.

Do not change LiteLLM config unless the failure is proven to be in the LiteLLM
entry model. Normal routing quality work should be contained inside IntentMux.

## 0.1.0 Readiness

IntentMux is ready to call itself log-driven when:

- daily health and strict E2E run reliably against production;
- review candidates are generated from mounted audit logs;
- at least one human-redacted production review batch has entered eval;
- route bank changes require a quality report;
- production rollout uses the documented gate and observes fresh logs after
  deployment.

This is a pre-release readiness target. It does not assign or imply a published
version number.
