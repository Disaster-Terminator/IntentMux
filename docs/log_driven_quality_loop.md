# Log-Driven Quality Loop

IntentMux uses production metadata to explain routing drift, low-confidence
decisions, failures, and latency regressions. Prompt review logs are optional
local-only evidence when explicitly enabled. Production logs, prompt review, and
AI-assisted review are operational triage inputs, not routing-quality ground
truth, and are not a standing pipeline for expanding eval cases or route banks.

`examples/eval_bank.sample.yaml` is the tracked public example for regression
and baseline comparison. Generated `data/semantic_sets/eval_bank.yaml` is a
local or production asset and remains git-ignored by default. Both can verify
that route-bank samples enter the router, but neither is proof of general
Chinese routing quality. `config/eval_cases.yaml` remains a smaller smoke suite
for quick contract checks. Production quality reports should prefer current-day
logs or logs produced after the `lite` / `deep` migration; full-history reports
may contain legacy `fast` / `strong` records and should be used only as
background context.

## Boundary

The route audit log is metadata only. It may contain `request_id`, `route_id`,
`target_model`, `reason`, scores, upstream status, and timing fields. It must
not contain raw prompts, completions, request bodies, bearer credentials,
provider keys, or LiteLLM secrets. Non-streaming OpenAI-compatible `usage`
counts such as `prompt_tokens`, `completion_tokens`, and `total_tokens` may be
recorded as numeric metadata; IntentMux does not calculate provider cost.

Route audit records also include safe configuration provenance when available:
`config_source`, `config_sha256`, and `route_bank_sha256`. These hashes let
operators attribute traffic changes to a specific runtime config and semantic
route bank without logging local paths or private config contents.

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
  -> optional local AI review packet for operational triage
  -> public dataset regression report for any routing-policy change
  -> production rollout gate for bug fixes or explicitly justified changes
  -> observe new logs
```

## Review Candidate Selection

Use `scripts/router_log_summary.py --window-minutes N` for sliding-window
metadata triage before deeper review. The window is anchored to the latest
timestamp in the selected input, so archived log slices remain reproducible:

```bash
uv run python scripts/router_log_summary.py /data/logs/routes/*.jsonl \
  --window-minutes 15 \
  --json
```

Directory inputs are auto-discovered for common runtime layouts such as
`logs/routes/*.jsonl` and dated `cloud-route-audits/*/*.jsonl`; discovery is
bounded with `--max-files` so cloud snapshots do not accidentally expand into
unbounded full-history scans. JSON output includes low-risk `candidate_clusters`
derived from route metadata only.

For a live process without log shipping, `/v1/intentmux/status` exposes safe
runtime config shape and `/v1/intentmux/counters` exposes low-cardinality
in-process counters. These endpoints are diagnostic surfaces only; they do not
replace external monitoring, persistent route audit logs, or daily quality
reports. In cloud mode they require IntentMux inbound auth and omit local paths,
raw target model names, raw hard-rule keywords, prompts, responses, and keys.
Outside cloud mode these diagnostic endpoints also require inbound auth whenever
`ROUTER_INBOUND_API_KEY` or rotation keys are configured.

Use `scripts/select_review_candidates.py` to select metadata-only records for
bounded operational triage:

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

The report also includes `candidate_clusters`, grouped by safe route metadata
such as route, reason, top/second route, `match_source`, `match_index`, and
`match_text_sha256`. Start triage from these clusters before reading individual
candidate rows: a repeated cluster is stronger evidence than a one-off near
threshold request, and it keeps review focused without exposing prompt text.

When prompt review logs are passed with `--prompt-path`, the script joins them
by `request_id` and only reports whether a candidate has matching local review
evidence, whether that evidence was truncated, and the prompt character count.
It does not print prompt text or infer framework identity from prompt contents.

The output is intentionally limited to route metadata and safe structural
signals:

```json
{
  "summary": {
    "candidate_clusters": [
      {
        "count": 12,
        "route_id": "lite",
        "reason": "low_confidence",
        "top_route_id": "deep",
        "second_route_id": "lite",
        "match_source": "swebench_issue_resolution",
        "match_index": 970,
        "match_text_sha256": "..."
      }
    ]
  },
  "candidates": [
    {
      "request_id": "req-...",
      "timestamp": "2026-05-13T00:00:00Z",
      "config_source": "ROUTER_CONFIG",
      "config_sha256": "...",
      "route_bank_sha256": "...",
      "route_id": "lite",
      "target_model": "lite-upstream",
      "reason": "low_confidence",
      "score": 0.53,
      "second_score": 0.51,
      "prompt_tokens": 1000,
      "completion_tokens": 250,
      "total_tokens": 1250,
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
  ]
}
```

`format_signals` are derived from OpenAI-compatible request structure, not from
private prompt text. Generic agent-like structure such as `tools`,
`tool_history`, `tool_choice`, and long multi-turn context is audit evidence,
not a hard route decision. Treat these records as review candidates when they
cluster around `low_confidence`, high latency, or unexpected `deep` call-rate
changes, but do not promote request structure alone into a `deep` route.

## AI Review Packet

AI review packets are local-only operational triage artifacts. They can help an
operator summarize repeated failure clusters, but they are not labels and do
not by themselves justify route-bank, threshold, margin, or hard-rule changes.

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

## Route Replay

Replay is the offline reproducibility layer between raw production logs and
route-bank or threshold changes:

```bash
uv run python scripts/replay_routes.py /data/logs/prompts/*.jsonl \
  --routes /data/config/routes.yaml \
  --limit 100 \
  --json-output /data/reports/replay/intentmux-replay-YYYY-MM-DD.json \
  --markdown-output /data/reports/replay/intentmux-replay-YYYY-MM-DD.md
```

It replays the same local samples through `current-router`, `always-lite`,
`always-deep`, and `hard-rule-only`. This follows the RouteLLM / router
benchmark lesson: judge routing changes by quality evidence, cost-tier
distribution, and simple baselines together. Historical route ids in prompt
review logs are drift evidence, not ground truth labels unless the replay input
was explicitly labeled. By default replay reports include text hashes and
character counts, not raw prompt text. Replay also emits compact
old-vs-current deltas for the current router: route, reason, target model, and
match source changes. The CLI samples at most 100 cases by default; use
`--limit N` for a smaller batch or `--limit 0` for an explicit unbounded local
run. Default terminal output is a compact summary; write `--json-output` or
`--markdown-output` for full cases. Use `--include-text` only with an explicit
private local output file. Replay calls the configured embedding endpoint, so
it only allows localhost, private addresses, or `host.docker.internal` by
default; use `--allow-remote-embeddings` only for trusted private review runs.

Route eval follows the same default: stdout and JSON output use case ids,
hashes, and character counts. Use `eval_routes.py --include-text` only for a
private local run that needs raw eval text in stdout or JSON.

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
- public/reproducible dataset evidence for the behavior being changed;
- candidate review evidence only as operational context, not ground truth;
- rollback plan limited to IntentMux config, assets, or image.

Do not change LiteLLM config unless the failure is proven to be in the LiteLLM
entry model. Normal routing quality work should be contained inside IntentMux.

## 0.1.0 Readiness

IntentMux is ready to call itself log-driven when:

- daily health and strict E2E run reliably against production;
- review candidates are generated from mounted audit logs;
- AI review packets and summaries are generated from mounted audit logs;
- private production review is clearly marked operational-only;
- route bank changes require public/reproducible eval evidence and a quality
  report;
- production rollout uses the documented gate and observes fresh logs after
  deployment.

This is a pre-release readiness target. It does not assign or imply a published
version number.

The current lightweight quality-loop work order is controlled by
`docs/PROJECT_CONTROL.md`. Archived dated plans are historical context only.
