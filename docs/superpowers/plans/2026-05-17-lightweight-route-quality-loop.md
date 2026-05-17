# Lightweight Route Quality Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make IntentMux route quality work usable in daily dogfood by reusing existing logs, eval, review-candidate, and quality-report scripts, without building an unsustainable custom dataset.

**Architecture:** Keep IntentMux as a lightweight two-tier router. Treat existing eval cases as regression tests, not proof of general router quality. Add a daily quality loop that produces agent-reviewed summaries and human-escalation notes from route logs and optional prompt review logs; route changes remain blocked until the report shows a concrete regression or repeated actionable pattern.

**Tech Stack:** Python, uv, JSONL route audit logs, optional local prompt review logs, YAML eval cases, `scripts/eval_routes.py`, `scripts/router_log_summary.py`, `scripts/select_review_candidates.py`, `scripts/route_quality_report.py`, `scripts/intentmux_daily_health.py`.

---

## Decision

Reuse the previous Chinese semantic routing plan as background only. Do not execute it as a data-construction plan.

The old plan correctly identified useful primitives:

- route eval output;
- slice/product metrics;
- production review candidates;
- source/license boundaries;
- route-quality reports;
- production rollout gate.

The old plan was too heavy in one direction: it implied that IntentMux should build a Chinese intent-routing dataset before the router can improve. That is outside the current project capacity and risks creating low-quality subjective labels.

The revised plan is operational:

1. keep the current route mechanism;
2. run regression evals;
3. summarize real traffic;
4. select review candidates;
5. let an agent pre-review candidates and produce a compact human-auditable report;
6. add only reviewed, redacted, high-value cases to regression fixtures;
7. compare current router behavior to simple baselines before changing route rules.

## Product Boundary

IntentMux should not become RouteLLM, RouterBench, Semantic Router, or a training system.

IntentMux should be:

- a lightweight local `auto` / `lite` / `deep` router;
- cost-first by default;
- explicit-route friendly;
- LiteLLM-compatible but not LiteLLM-dependent;
- safe to dogfood locally;
- improved from logs and regression cases rather than broad manual dataset work.

## Review Model

Pure human review is too expensive. Pure agent review is not trustworthy enough.

The intended loop is:

```text
route audit logs
  -> deterministic candidate selection
  -> optional prompt review lookup by request_id
  -> agent pre-review summary
  -> human sees only escalation notes and representative evidence
  -> human can audit the raw local prompt when needed
  -> redacted regression case, if useful
```

Agent review must not directly edit route banks, thresholds, hard rules, or production config. It produces:

- suspected route mistakes;
- repeated low-confidence patterns;
- broad hard-rule overreach candidates;
- privacy-safe summaries;
- explicit "needs human decision" items.

The public repository should not hard-code Retinue, Hermes, OpenCode, or
RayStorm-only paths. Instead, repository scripts should prepare a local private
review packet that any downstream agent runner can read. RayStorm's local cron
can feed that packet to Retinue/Hermes and write the resulting agent summary
beside runtime logs.

The human operator should only need to inspect:

- cases where the agent is uncertain;
- cases that would change route policy;
- cases that might contain private prompt material;
- repeated failures that would justify adding regression cases.

## What Existing Facilities Can Be Reused

### `scripts/eval_routes.py`

Reuse as the regression eval runner. It already runs the real `Router` and can use real embeddings. It should remain small and deterministic.

Current limitation: default `config/eval_cases.yaml` is smoke-level and has no slice metadata. It is useful for regressions, not quality proof.

### `scripts/router_log_summary.py`

Reuse as the traffic summary source for quality reports. It should be the input to `route_quality_report.py`, not the whole daily health JSON.

Current limitation: full-history summaries include legacy `fast` / `strong` routes, so quality work should prefer current-day or post-migration logs.

### `scripts/select_review_candidates.py`

Reuse as deterministic candidate selection. It already selects:

- `low_confidence`;
- `embedding_error`;
- route errors;
- upstream non-2xx responses;
- near threshold;
- near margin;
- slow requests;
- hard-rule hits.

Current limitation: it intentionally avoids prompt text. That is correct for public artifacts, but agent pre-review needs a local-only mode that can read prompt review logs and produce a private report.

### `scripts/route_quality_report.py`

Reuse as the quality report core. It already combines eval results with route traffic summary and reports product metrics.

Current limitation: it has no baseline comparison and is not wired into daily health outputs.

### `scripts/intentmux_daily_health.py`

Reuse as the daily orchestration point. It already knows production paths, readiness, route budgets, log consistency, and E2E.

Current limitation: it does not yet produce a quality report or agent-review handoff.

## Non-Goals

- Do not build a large custom Chinese dataset.
- Do not train a router model.
- Do not bulk-translate benchmarks and call them Chinese quality data.
- Do not make route changes from agent review alone.
- Do not put raw prompts in git, stdout, daily health, or public reports.
- Do not hard-code RayStorm-only paths into public examples.
- Do not rebuild the production container for plan-only or docs-only work.

## Implementation Plan

### Task 1: Separate Regression Eval From Quality Claims

**Files:**

- Modify: `docs/route_quality_evidence_status.md`
- Modify: `docs/log_driven_quality_loop.md`
- Modify: `README.md`

- [ ] State that `config/eval_cases.yaml` is a regression/smoke suite, not a benchmark.
- [ ] State that production quality reports must prefer current-day or post-migration logs.
- [ ] Link the daily quality loop plan from the existing quality docs.
- [ ] Verify with `git diff -- docs/route_quality_evidence_status.md docs/log_driven_quality_loop.md README.md`.

### Task 2: Add Baseline Evaluation Modes

**Files:**

- Modify: `scripts/eval_routes.py`
- Modify: `tests/test_eval_routes.py`

Add a small baseline abstraction that can run the same cases through:

- `current-router`;
- `always-lite`;
- `always-deep`;
- `hard-rule-only`.

The first implementation should not add a trainable model, judge model, or outcome scoring. It only compares route choices for the same regression cases.

Expected CLI shape:

```bash
uv run python scripts/eval_routes.py \
  --cases config/eval_cases.yaml \
  --json-output /tmp/intentmux-eval.json \
  --baseline current-router
```

and:

```bash
uv run python scripts/eval_routes.py \
  --cases config/eval_cases.yaml \
  --json-output /tmp/intentmux-eval-always-lite.json \
  --baseline always-lite
```

TDD checklist:

- [ ] Add tests that `always-lite` routes every case to `lite`.
- [ ] Add tests that `always-deep` routes every case to `deep`.
- [ ] Add tests that `hard-rule-only` routes hard-rule matches to `deep` and all other cases to fallback `lite`.
- [ ] Preserve the existing default behavior as `current-router`.
- [ ] Keep JSON schema backward-compatible by adding `baseline` at top level and per case.

Validation:

```bash
uv run pytest tests/test_eval_routes.py -q
uv run python scripts/eval_routes.py --mock-embeddings --baseline current-router
uv run python scripts/eval_routes.py --mock-embeddings --baseline always-lite
uv run python scripts/eval_routes.py --mock-embeddings --baseline always-deep
uv run python scripts/eval_routes.py --mock-embeddings --baseline hard-rule-only
```

### Task 3: Teach Quality Report To Compare Baselines

**Files:**

- Modify: `scripts/route_quality_report.py`
- Modify: `tests/test_route_quality_report.py`

Add optional multiple eval inputs:

```bash
uv run python scripts/route_quality_report.py \
  --eval-json current=/tmp/current.json \
  --eval-json always-lite=/tmp/always-lite.json \
  --eval-json always-deep=/tmp/always-deep.json \
  --route-summary-json /tmp/route-summary.json \
  --json-output /tmp/quality.json \
  --markdown-output /tmp/quality.md
```

If multiple eval files are provided:

- keep the current eval section for the first or `current` report;
- add a `baselines` section with pass rate, expected/actual distribution, and deep call rate per baseline;
- render the same in markdown.

This remains a regression comparison, not proof of general quality.

Validation:

```bash
uv run pytest tests/test_route_quality_report.py -q
```

### Task 4: Add Local Agent Review Report

**Files:**

- Create: `scripts/prepare_agent_review_packet.py`
- Create: `scripts/summarize_agent_review.py`
- Create: `tests/test_agent_review_candidates.py`
- Modify: `docs/log_driven_quality_loop.md`

Create a local-only agent review interface in two pieces.

First, `prepare_agent_review_packet.py` reads the candidate JSON produced by
`select_review_candidates.py` and optional prompt review logs, then produces a
packet designed for an agent to read. By default, the packet contains metadata
only. With an explicit local-only flag, it may include prompt excerpts from
`ROUTER_PROMPT_LOG_DIR`; those outputs must be written under runtime logs and
must remain gitignored.

Second, `summarize_agent_review.py` reads a structured agent result file and
produces a compact human-auditable markdown summary. This keeps the repository
generic: the actual LLM/agent runner can be Retinue, Hermes, OpenCode, Codex, or
another local automation layer.

Packet groups:

- `needs_human_decision`: hard-rule hits, route errors, upstream non-2xx, or repeated slow requests;
- `likely_regression_case`: low-confidence or near-margin cases with prompt review evidence;
- `watch_only`: low-confidence cases without prompt review evidence;
- `privacy_blocked`: candidates where prompt review exists but is truncated or local-only raw text is required before deciding.

The packet should include:

- counts by group;
- top candidate rows with request id, route, target, reason, score, second score, duration, prompt evidence metadata;
- no prompt text by default;
- optional prompt excerpts only when `--include-prompt-text raw_local` is passed;
- an explicit instruction block telling the downstream agent to summarize in Chinese even when the prompt is English;
- an explicit instruction block telling the downstream agent to escalate uncertainty rather than invent labels.

The agent result schema should allow:

- `request_id`;
- `agent_decision`: `route_ok`, `suspected_misroute`, `needs_human`, `privacy_blocked`, or `watch_only`;
- `confidence`: `high`, `medium`, or `low`;
- `suggested_expected_route`: `lite`, `deep`, or `unknown`;
- `summary_zh`;
- `evidence`;
- `human_decision_required`;
- `redaction_required`.

`summarize_agent_review.py` should output:

- counts by `agent_decision`;
- high-priority human decisions;
- suspected regression cases;
- privacy-blocked cases;
- no raw prompt text unless the input itself is a local-only raw report and the output path is outside the repository.

This is agent-assisted review, not auto-labeling. Agent output can suggest a
regression case, but only a redacted case should enter `import_review_samples.py`.

Validation:

```bash
uv run pytest tests/test_agent_review_candidates.py -q
uv run python scripts/prepare_agent_review_packet.py \
  --input /tmp/intentmux-review-candidates.json \
  --json-output /tmp/intentmux-agent-review-packet.json \
  --markdown-output /tmp/intentmux-agent-review-packet.md
uv run python scripts/summarize_agent_review.py \
  --input tests/samples/agent_review_result.synthetic.json \
  --json-output /tmp/intentmux-agent-review-summary.json \
  --markdown-output /tmp/intentmux-agent-review-summary.md
```

### Task 5: Wire Quality Outputs Into Daily Health

**Files:**

- Modify: `scripts/intentmux_daily_health.py`
- Modify: `tests/test_intentmux_daily_health.py`
- Modify: `docs/PATROL_HANDOFF.md`

Add optional quality output generation after route summary and log consistency:

- run regression eval with `current-router`;
- run simple baselines;
- run route log summary for the selected date;
- run route quality report;
- run candidate selection;
- prepare the local agent review packet;
- include paths where downstream cron/agent automation should write agent summaries.

Default behavior should be safe:

- quality report generation is enabled for local cron if paths exist;
- failures should be reported in the health JSON/MD but should not fail readiness unless explicitly configured;
- raw prompt text is never copied into health output.

Output paths should live near existing runtime logs:

```text
/data/logs/quality/intentmux-quality-YYYY-MM-DD.json
/data/logs/quality/intentmux-quality-YYYY-MM-DD.md
/data/logs/quality/intentmux-quality-latest.json
/data/logs/quality/intentmux-quality-latest.md
/data/reviews/agent/intentmux-agent-review-packet-YYYY-MM-DD.json
/data/reviews/agent/intentmux-agent-review-packet-YYYY-MM-DD.md
/data/reviews/agent/intentmux-agent-review-summary-YYYY-MM-DD.json
/data/reviews/agent/intentmux-agent-review-summary-YYYY-MM-DD.md
```

Local deployments can map `/data` to their own runtime directory. RayStorm's
Hermes cron wrapper should do that mapping outside the public repository.

Validation:

```bash
uv run pytest tests/test_intentmux_daily_health.py -q
uv run python scripts/intentmux_daily_health.py --output-dir /tmp/intentmux-health --skip-e2e
```

### Task 6: Local Deployment Sync Without Route Policy Changes

**Files:**

- Modify only local runtime files if needed.
- Do not modify LiteLLM config.
- Do not change `threshold`, `margin`, hard rules, or route bank.

After implementation:

```bash
uv run python -m ruff check .
uv run python -m pytest -q
uv run python scripts/eval_routes.py --mock-embeddings
uv run python scripts/verify_route_contract.py
```

Then, for local production only:

- run the daily health script once;
- verify quality report files exist;
- verify prompt text is not present in public health/quality markdown;
- do not rebuild the production container unless code executed inside the container must change.

## Acceptance Criteria

- Existing CI stays green.
- Daily quality artifacts can be generated from existing logs and eval cases.
- Quality artifacts clearly say when the eval set is only regression/smoke level.
- Baseline comparison exists for `always-lite`, `always-deep`, `hard-rule-only`, and `current-router`.
- Agent review produces a compact human-auditable summary without raw prompt text.
- The repository prepares an agent-review packet without depending on Retinue or Hermes.
- Local downstream automation can feed that packet to an agent and write a summary beside runtime logs.
- No production route policy changes are made in this plan.
- No public file contains RayStorm-only runtime paths except as clearly marked local evidence in internal docs.

## Follow-Up After This Plan

Only after the daily quality loop produces useful reports should we decide whether to:

- add a small number of redacted regression cases;
- adjust route bank examples;
- narrow or remove hard rules;
- tune threshold or margin;
- consider outcome-based eval for specific slices.

Those are separate changes and require before/after reports.

## Retinue Cross-Check Notes

A read-only Retinue review agreed that the existing pipeline is reusable:

- `scripts/select_review_candidates.py` for deterministic candidate selection;
- `scripts/router_log_summary.py` for traffic summaries;
- `scripts/eval_routes.py` for regression evals;
- `scripts/route_quality_report.py` for product metrics;
- `scripts/import_review_samples.py` for redacted sample import;
- `scripts/intentmux_daily_health.py` as the likely orchestration surface.

The review also flagged two risks that this plan treats as first-class:

- local overfitting to RayStorm/OpenCode/Retinue/Hermes traffic;
- private prompt leakage from raw local prompt review logs.
