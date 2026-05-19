# Log-Driven Quality Loop

IntentMux improves routing quality from production metadata, optional local
prompt review logs, external AI-assisted review, and redacted review samples.
Route audit logs identify routing drift, low-confidence decisions, failures,
and latency regressions; prompt review logs provide local-only semantic evidence
when explicitly enabled. Only reviewed, redacted samples are promoted into eval
cases or route banks.

`examples/eval_bank.sample.yaml` is the tracked public example for regression
and baseline comparison. Generated `data/semantic_sets/eval_bank.yaml` is a
local or production asset and remains git-ignored by default. Both can verify
that route-bank samples enter the router, but neither is proof of general
Chinese routing quality. `config/eval_cases.yaml` remains a smaller smoke suite
for fast contract checks. Production quality reports should prefer current-day
logs or logs produced after the `lite` / `deep` migration; full-history reports
may contain legacy `fast` / `strong` records and should be used only as
background context.

## Boundary

The route audit log is metadata only. It may contain `request_id`, `route_id`,
`target_model`, `reason`, scores, upstream status, and timing fields. It must
not contain raw prompts, completions, request bodies, token usage, bearer
credentials, provider keys, or LiteLLM secrets.

For accepted embedding decisions, the route audit log and decision endpoint may
also contain `match_source`, `match_index`, and `match_text_sha256`. These fields
identify the loaded route-bank sample that won the semantic match without
logging the matched sample text. Hard rules, explicit route overrides,
low-confidence fallback, and passthrough decisions do not claim a semantic
sample match.

`match_score` and `match_provenance` describe how that sample attribution was
computed. With the default Aurelio hybrid kernel, `aurelio_hybrid_exact` means
the attribution used the same dense-plus-sparse local scoring shape as the
hybrid route decision. This keeps audit evidence separate from IntentMux's
product decision: Aurelio supplies the matching kernel; IntentMux owns the
two-tier `lite` / `deep` contract, score gates, logs, and learning workflow.
`match_source=inline_config` means the matched sample came from the active
routes.yaml seed utterances rather than a route-bank dataset.

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
  -> AI review packet for an external reviewer
  -> human audit for escalations, uncertainty, and policy changes
  -> redacted production_review JSONL
  -> eval bank import
  -> route bank / threshold / margin change
  -> route quality report
  -> production rollout gate
  -> observe new logs
```

## Review Candidate Selection

Use `scripts/select_review_candidates.py` to select metadata-only records that
deserve AI review and possible human audit:

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
  "route_id": "lite",
  "target_model": "lite-upstream",
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
private prompt text. Generic agent-like structure such as `tools`,
`tool_history`, `tool_choice`, and long multi-turn context is audit evidence,
not a hard route decision. Treat these records as review candidates when they
cluster around `low_confidence`, high latency, or unexpected `deep` call-rate
changes, but do not promote request structure alone into a stronger-tier route.

## AI Review Packet

Generate a local-only packet for an external AI reviewer:

```bash
uv run python scripts/prepare_ai_review_packet.py \
  --input /data/reviews/intentmux-review-candidates-YYYY-MM-DD.json \
  --json-output /data/reviews/agent/intentmux-ai-review-packet-YYYY-MM-DD.json \
  --markdown-output /data/reviews/agent/intentmux-ai-review-packet-YYYY-MM-DD.md
```

The default packet is metadata-only. Raw prompt excerpts require the explicit
`--include-prompt-text raw_local` flag and should only be written under a local
private runtime directory.

Validate and summarize AI output:

```bash
uv run python scripts/summarize_ai_review.py \
  --input /data/reviews/agent/intentmux-ai-review-result-YYYY-MM-DD.json \
  --json-output /data/reviews/agent/intentmux-ai-review-summary-YYYY-MM-DD.json \
  --markdown-output /data/reviews/agent/intentmux-ai-review-summary-YYYY-MM-DD.md
```

These scripts do not call an AI provider and are not part of the request-time
routing path. The repository prepares and validates generic artifacts; local
automation decides which external AI runner reads the packet.

## Promoting Samples

Candidate records do not become eval cases automatically. AI may summarize and
classify candidates first, but a human must review any item that would change
routing policy, expose private prompt material, or introduce a subjective
label. Accepted examples must be private-content-free representative prompts
with `redacted: true`.

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

Every imported sample must use a product `route_id` such as `lite` or `deep`
as `expect`; deployment-side target model names such as `lite-upstream` and
`deep-upstream` must not be used as eval labels.

Local production review JSONL files are deployment artifacts and are ignored by
git. Keep only curated public examples such as
`data/source_samples/production_review.example.jsonl` in the repository.

## Change Gate

Any route bank, threshold, margin, or hard-rule change should include:

- route eval JSON for `current-router` plus simple baselines such as
  `always-lite`, `always-deep`, and `hard-rule-only`;
- the eval cases path, normally generated `data/semantic_sets/eval_bank.yaml`
  in production or `examples/eval_bank.sample.yaml` in a clean clone;
- route log summary from current-day or post-migration production traffic;
- `scripts/route_quality_report.py` JSON/Markdown output;
- candidate review evidence when the change is production-log driven;
- rollback plan limited to IntentMux config, assets, or image.

Do not change LiteLLM config unless the failure is proven to be in the LiteLLM
entry model. Normal routing quality work should be contained inside IntentMux.

## 0.1.0 Readiness

IntentMux is ready to call itself log-driven when:

- daily health and strict E2E run reliably against production;
- review candidates are generated from mounted audit logs;
- AI review packets and summaries are generated from mounted audit logs;
- at least one accepted, redacted production review batch has entered eval;
- route bank changes require a quality report;
- production rollout uses the documented gate and observes fresh logs after
  deployment.

This is a pre-release readiness target. It does not assign or imply a published
version number.

The current lightweight quality-loop work order is controlled by
`docs/PROJECT_CONTROL.md`. Archived dated plans are historical context only.
