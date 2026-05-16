# Chinese Semantic Routing Learning Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn IntentMux Chinese routing quality work into a reproducible, evidence-driven learning loop instead of guessing route rules from a small local sample.

**Architecture:** IntentMux stays a lightweight `auto` / `lite` / `deep` router. Mature router projects are used for method discipline: define route labels, measure errors, calibrate thresholds, and promote changes through a report gate. Public Chinese datasets are treated as source material with license boundaries; private production prompts remain local review evidence until redacted and approved.

**Tech Stack:** Python, uv, YAML route/eval assets, structured route logs, prompt review logs, `scripts/build_zh_route_eval.py`, `scripts/eval_routes.py`, `scripts/route_quality_report.py`, LiteLLM-compatible production sidecar.

---

## Why This Plan Exists

The previous direction was too close to engineering intuition. The hard product problem is not "add more rules"; it is how to learn Chinese `lite` / `deep` routing behavior when there is no mature Chinese semantic router to copy.

This plan treats the project as an empirical loop:

1. collect safe source material;
2. label it under IntentMux product semantics;
3. evaluate current routing behavior;
4. inspect production misses;
5. make one small routing change;
6. prove whether the change improved the measured behavior.

If a step cannot produce evidence, it does not change production routing.

## Research Baseline

### Borrowed Method Patterns

- Semantic Router validates the route-utterance approach: routes have example utterances, an encoder, route score thresholds, `evaluate`, and `fit`. The useful lesson for IntentMux is not to import the dependency, but to keep route examples and threshold changes measurable.
- RouteLLM confirms the two-tier cost-quality framing: route between a stronger and weaker model, calibrate a threshold to control strong-model call rate, and evaluate routers on benchmark tasks. The useful lesson for IntentMux is to measure `deep_call_rate` against quality metrics, not to train a heavy preference router now.
- General router benchmarks should be treated as methodology references. They do not solve Chinese routing labels for us, and English benchmark accuracy is not a substitute for Chinese local-agent traffic behavior.

### Current Repo Evidence

- `docs/PROJECT_IDENTITY.md` defines current public entries as `auto`, `lite`, and `deep`.
- `docs/roadmap.md` says semantic assets should come from mature datasets plus redacted production review samples, not self-generated corpora.
- `config/route_sources.yaml` is the route-bank source manifest. Current redistributable sources are MASSIVE zh-CN / zh-TW for `lite`, and SWE-bench / MBPP / HumanEval for `deep`.
- `config/zh_route_eval_sources.yaml` is the Chinese eval source manifest. It already separates permissive assets from manifest-only or review-required assets.
- `scripts/build_zh_route_eval.py` validates Chinese eval slices and only accepts `lite` / `deep` route labels.
- `scripts/route_quality_report.py` already reports product metrics such as `lite_general_keep_rate`, `lite_precision`, `deep_recall_high_risk`, `deep_recall_code`, `low_confidence_rate`, `near_margin_rate`, and `deep_call_rate`.
- `docs/router_quality_research.md` and `docs/zh_route_eval_plan.md` still contain stale `fast` / `strong` language and should be updated before they are used as public direction.

## Source Policy

### Tier A: Route-Bank Candidates

These may be used to build public or reproducible route-bank samples when attribution is preserved:

| source | route | why usable | current file |
| --- | --- | --- | --- |
| MASSIVE zh-CN / zh-TW | `lite` | Chinese assistant-style utterances, CC-BY-4.0 | `config/route_sources.yaml` |
| MBPP | `deep` | code-generation task prompts, CC-BY-4.0 | `config/route_sources.yaml` |
| HumanEval | `deep` | code prompts, MIT | `config/route_sources.yaml` |
| SWE-bench issue statements | `deep` | real software issue resolution, MIT | `config/route_sources.yaml` |
| curated public/redacted samples | reviewed `lite` or `deep` | project-owned Apache-2.0 samples | `data/source_samples/*.example.*` |

Weakness: only MASSIVE is Chinese-native in the current route bank. The `deep` side still depends heavily on English code benchmarks plus local curated Chinese examples. That is acceptable for now only if the eval report makes this limitation visible.

### Tier B: Eval-Only or Manifest-Only Candidates

These can inform the benchmark shape, but must not be committed as derived route-bank data until license and redistribution risk is resolved:

| source | likely route | current risk |
| --- | --- | --- |
| C-Eval | `deep` reasoning | dataset is CC-BY-NC-SA-4.0; keep manifest-only unless use is explicitly approved |
| CMMLU | `deep` reasoning | dataset is CC-BY-NC-SA-4.0; keep manifest-only unless use is explicitly approved |
| LongBench Chinese | `deep` long context | useful for long context, but license/use policy needs review before committing derived samples |
| DataCLUE / CLUE intent data | `lite` intent | review-required; do not ingest blindly |
| SuperCLUE-Code3 | `deep` code | review-required; do not ingest blindly |

### Tier C: Production-Local Evidence

Raw production prompts are not public assets. They are only local evidence for human review. A production sample can enter eval only after:

- it is selected by metadata or prompt-review tooling;
- a human reads it in the local environment;
- private content is removed;
- the resulting prompt is rewritten as a representative example;
- `redacted: true` and source metadata are recorded.

## Learning Questions

1. Can `lite` and `deep` be separated reliably for Chinese local-agent traffic, or do many cases require explicit caller override?
2. Which Chinese-native public sources can legally enter route-bank data, and which must remain eval-only or manifest-only?
3. What is the minimum local production review batch size that reveals stable route errors: 20, 50, or 100 reviewed samples?
4. Are current failures caused by missing utterances, weak threshold/margin calibration, hard-rule overreach, or request-format policy?
5. How much `deep_call_rate` is acceptable if `deep_recall_high_risk` and `deep_recall_code` stay high?
6. Can the route bank improve Chinese behavior without overfitting to RayStorm-only Retinue traffic?

## Product Metrics

The first quality gate should not optimize one global accuracy number. Use slice metrics:

- `deep_recall_high_risk`: must stay very high; misses are production-risk regressions.
- `deep_recall_code`: should catch code-editing, review, debugging, and agent tasks.
- `lite_general_keep_rate`: protects low-risk Chinese requests from drifting into `deep`.
- `lite_precision`: checks whether actual `lite` decisions are safe.
- `low_confidence_rate`: shows whether the embedding bank is underspecified.
- `near_margin_rate`: shows threshold instability.
- `hard_rule_hit_rate`: detects over-dominant keyword or format rules.
- `deep_call_rate`: tracks cost and product semantics.

Initial thresholds should be treated as provisional. Do not freeze numeric targets until at least one reviewed local batch and one public eval batch exist.

## Non-Goals

- Do not train a router model in this round.
- Do not self-generate Chinese corpora with an LLM and treat them as evidence.
- Do not bulk-translate English benchmarks and call the result Chinese-native quality.
- Do not promote `C-Eval`, `CMMLU`, `LongBench`, `DataCLUE`, or `SuperCLUE-Code3` samples into committed route banks before license review.
- Do not change production route thresholds, margins, hard rules, or route-bank assets without a before/after quality report.
- Do not collapse product routing into Retinue-specific behavior. Retinue traffic is useful evidence, but not the product definition.

## Implementation Plan

### Task 1: Reconcile Public Quality Docs

**Files:**
- Modify: `docs/router_quality_research.md`
- Modify: `docs/zh_route_eval_plan.md`
- Test: documentation diff review

- [ ] **Step 1: Replace stale terminology**

Update both files to use `lite` / `deep` as canonical route labels. Keep `fast` / `strong` only as explicitly named legacy aliases when needed.

- [ ] **Step 2: Add the data-source tier policy**

Copy the Tier A / Tier B / Tier C distinction into `docs/router_quality_research.md` in concise form. The doc should say which sources can build route banks and which remain manifest-only.

- [ ] **Step 3: Add method references**

Link the public references used here:

- Semantic Router threshold optimization: `https://docs.aurelio.ai/semantic-router/user-guide/features/threshold-optimization`
- RouteLLM: `https://github.com/lm-sys/RouteLLM`
- RouteLLM paper: `https://arxiv.org/abs/2406.18665`
- MASSIVE: `https://www.amazon.science/code-and-datasets/massive`
- C-Eval: `https://github.com/hkust-nlp/ceval`
- CMMLU: `https://github.com/haonan-li/CMMLU`
- LongBench: `https://github.com/THUDM/LongBench`

- [ ] **Step 4: Verify the docs**

Run:

```bash
git diff -- docs/router_quality_research.md docs/zh_route_eval_plan.md
```

Expected: no remaining `fast` / `strong` wording except explicit legacy-alias discussion.

### Task 2: Add a Source-Audit Report Command

**Files:**
- Modify: `scripts/build_zh_route_eval.py`
- Add or modify tests: `tests/test_build_zh_route_eval.py`

- [ ] **Step 1: Add tests for source classification**

Add a test that loads a manifest with one `sample_only`, one `manifest_only`, and one `never` source and asserts the summary groups them by `commit_policy`, `commercial_use`, and `redistributable`.

- [ ] **Step 2: Implement a pure function**

Add:

```python
def summarize_source_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    validate_source_manifest(manifest)
    summary = {
        "total": 0,
        "by_commit_policy": {},
        "route_bank_candidates": [],
        "manifest_only": [],
        "blocked": [],
    }
    for source in manifest["sources"]:
        summary["total"] += 1
        policy = source["commit_policy"]
        summary["by_commit_policy"][policy] = summary["by_commit_policy"].get(policy, 0) + 1
        item = {
            "name": source["name"],
            "slice": source["slice"],
            "route": source["route"],
            "license_id": source["license_id"],
            "redistributable": source["redistributable"],
            "commercial_use": source["commercial_use"],
            "commit_policy": policy,
        }
        if policy == "sample_only" and source["redistributable"] and source["commercial_use"]:
            summary["route_bank_candidates"].append(item)
        elif policy == "manifest_only":
            summary["manifest_only"].append(item)
        else:
            summary["blocked"].append(item)
    return summary
```

- [ ] **Step 3: Expose the summary from CLI**

Add optional arguments:

```text
--source-manifest config/zh_route_eval_sources.yaml
--source-summary-json /tmp/zh_sources.json
```

When these are passed, write the summary JSON without requiring `--curated-samples`.

- [ ] **Step 4: Verify**

Run:

```bash
uv run pytest tests/test_build_zh_route_eval.py -q
uv run python scripts/build_zh_route_eval.py \
  --source-manifest config/zh_route_eval_sources.yaml \
  --source-summary-json /tmp/intentmux-zh-source-summary.json
```

Expected: tests pass and the JSON clearly separates route-bank candidates from manifest-only sources.

### Task 3: Produce a Current Baseline Quality Report

**Files:**
- No production config changes
- Temporary outputs under `/tmp`

- [ ] **Step 1: Build the current tiny sample eval bank**

Run:

```bash
uv run python scripts/build_zh_route_eval.py \
  --curated-samples data/source_samples/zh_route_eval_v1.sample.yaml \
  --output /tmp/zh_route_eval_v1.sample.yaml
```

Expected: writes the sample eval bank with the current curated cases.

- [ ] **Step 2: Evaluate current routing**

Run:

```bash
uv run python scripts/eval_routes.py \
  --config config/routes.yaml \
  --cases /tmp/zh_route_eval_v1.sample.yaml \
  --json-output /tmp/zh_route_eval_v1.results.json
```

Expected: JSON result exists and every case has `expect`, `actual_route`, `reason`, and pass/fail fields.

- [ ] **Step 3: Generate the report**

Run:

```bash
uv run python scripts/route_quality_report.py \
  --eval-json /tmp/zh_route_eval_v1.results.json \
  --routes config/routes.yaml \
  --json-output /tmp/zh_route_quality.json \
  --markdown-output /tmp/zh_route_quality.md
```

Expected: report includes product metrics. Treat it as a baseline, not as proof of readiness because the sample is tiny.

### Task 4: Design the First Production Review Batch

**Files:**
- Modify: `docs/log_driven_quality_loop.md`
- Maybe modify: `scripts/select_review_candidates.py`
- Test if script changes: relevant pytest file

- [ ] **Step 1: Define the review batch**

Document the first batch as 20 to 50 local samples selected from:

- `low_confidence`;
- `near_margin`;
- high `deep_call_rate` periods;
- requests with `agent_signal`;
- `lite` decisions with long context or tool-use structure;
- `deep` decisions caused only by keyword/hard-rule.

- [ ] **Step 2: Keep private prompts local**

Document that prompt text can appear in the local review artifact only when prompt review logging is explicitly enabled. The public or committed artifact must contain only redacted representative prompts.

- [ ] **Step 3: Add missing selector signals only if needed**

If `scripts/select_review_candidates.py` cannot select the above cases from existing metadata, add a small focused change. Do not add prompt-text heuristics.

- [ ] **Step 4: Verify**

Run the selector against recent local logs and inspect the candidate markdown manually. Do not commit local outputs.

### Task 5: First Calibration Experiment

**Files:**
- Modify only after Tasks 1 to 4 have evidence
- Candidate files: `config/routes.yaml`, generated deployment route bank assets, or curated eval samples
- Test: routing eval and quality report

- [ ] **Step 1: Choose one change type**

Pick exactly one:

- add audited route utterances;
- adjust route thresholds;
- adjust margin;
- narrow an overbroad hard rule;
- add a request-format policy for generic agent workload.

- [ ] **Step 2: Run before/after eval**

Generate quality reports before and after the change. Compare:

- `deep_recall_high_risk`;
- `deep_recall_code`;
- `lite_general_keep_rate`;
- `lite_precision`;
- `low_confidence_rate`;
- `near_margin_rate`;
- `hard_rule_hit_rate`;
- `deep_call_rate`.

- [ ] **Step 3: Promote only if the report is better**

Promotion requires:

- no high-risk or code recall regression;
- no unexplained `deep_call_rate` jump;
- lower `low_confidence_rate` or fewer reviewed misses;
- a rollback plan limited to IntentMux config/assets/image.

## Immediate Next Goal Candidate

After this plan is reviewed, the next autonomous goal should be:

> Make the Chinese routing quality loop auditable: update stale quality docs to `lite` / `deep`, add a source-audit summary command, run the current sample eval/report baseline, and document the first production review batch without changing production routing behavior.

This goal is intentionally not a release goal and not a routing-algorithm rewrite. It creates the measurement surface needed before we decide whether any routing change is justified.

## Cross-Check Notes

- Retinue was used in read-only mode. One data-risk scout completed and agreed with the repo-level classification: permissive route-bank sources are limited; several Chinese benchmark candidates are manifest-only or review-required. One broader planning scout stalled and was not used as evidence.
- Web research was used for current external-source verification. Sources consulted include Semantic Router docs, RouteLLM repo/paper, MASSIVE, C-Eval, CMMLU, and LongBench.
