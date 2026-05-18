# Default Corpus Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current bootstrap corpus with a simpler, auditable default baseline: Simplified Chinese first, English retained for ecosystem coverage, Retinue/log-derived prompts kept out of the public default unless reviewed and generalized.

**Architecture:** Keep `routes.yaml` as the only route-policy entry. Keep generated assets local and ignored. Change the source manifest and builders so default assets separate `route`, `eval`, and `calibration`, exclude zh-TW by default, and include Chinese `deep` examples only when they are license-safe or curated/redacted.

**Tech Stack:** Python 3.11+, uv, YAML/JSONL semantic assets, pytest, existing `scripts/build_semantic_assets.py`.

---

## Evidence

- Current local assets are still bootstrap-only:
  - `data/semantic_sets/route_bank.yaml`: `lite=120`, `deep=160`.
  - `lite` sources are `massive_zh_cn_general` and `massive_zh_tw_general`.
  - `deep` sources are all English: SWE-bench, MBPP, HumanEval.
  - `data/semantic_sets/eval_bank.yaml`: `lite=103`, `deep=104`, with zh-TW in `lite` and English-only `deep`.
- User traffic is biased:
  - Local logs include many Retinue/OpenCode prompts, often English.
  - These are useful dogfood evidence, but must not dominate the public default baseline.
- External references:
  - Semantic Router uses route examples, encoders, indexes, and threshold fitting.
  - RouteLLM treats routing as a two-model cost-quality tradeoff and calibrates thresholds from representative incoming queries.
  - C-Eval and CMMLU are Chinese reasoning eval sources, but both are NC/SA licensed and should be eval/calibration or local-only unless mapped and redistributed deliberately.
  - LongBench is bilingual and useful for long-context eval/calibration.
  - CS-Eval is relevant for security/high-risk slices, but its dataset is NC/SA and should not enter public default route bank.

## Decisions

1. Default public route/eval baseline is `zh-CN` plus limited English, not zh-TW.
2. `massive_zh_tw_general` is removed from default `config/route_sources.yaml`; zh-TW can return later as an optional source.
3. English remains in default sources, but English Retinue/OpenCode production prompts are not automatically promoted.
4. Chinese `deep` route examples should start as small curated/redacted samples, not direct bulk conversion from C-Eval/CMMLU/CS-Eval.
5. Full upstream datasets are not "online route bank". They are raw/normalized local artifacts; route bank stays smaller than eval/calibration.
6. Embedding cache comes after the corpus baseline. Initial cache backend is JSONL + manifest, not SQLite.

## Task 1: Manifest Cleanup

**Files:**
- Modify: `config/route_sources.yaml`
- Modify: `tests/test_build_semantic_assets.py`

- [ ] Remove `massive_zh_tw_general` from the default source manifest.
- [ ] Keep `massive_zh_cn_general` and `massive_en_us_general`.
- [ ] Add a manifest test asserting default sources do not include `zh-TW`.
- [ ] Keep route/eval generation behavior unchanged for remaining sources.

Verification:

```bash
uv run python -m pytest tests/test_build_semantic_assets.py tests/test_route_bank.py -q
```

## Task 2: Curated Simplified-Chinese Deep Seed

**Files:**
- Create: `data/source_samples/default_zh_cn_deep.example.yaml`
- Modify: `scripts/build_semantic_assets.py`
- Modify: `tests/test_build_semantic_assets.py`

- [ ] Add a small tracked public sample file with redacted, generic Simplified Chinese `deep` prompts.
- [ ] Support `curated_yaml` sources in `build_semantic_assets.py`.
- [ ] Add `deep_debug_zh`, `deep_security_zh`, and `deep_long_context_zh` slices as route/eval candidates.
- [ ] Ensure samples carry `language: zh-CN`, `slice`, `source`, `license`, and `proposed_use`.

Verification:

```bash
uv run python -m pytest tests/test_build_semantic_assets.py -q
```

## Task 3: Eval Split Guard

**Files:**
- Modify: `scripts/build_semantic_assets.py`
- Modify: `tests/test_build_semantic_assets.py`
- Modify: `docs/router_data_pipeline_research.md`

- [ ] Ensure route-bank records do not enter eval/calibration output unless explicitly marked as smoke.
- [ ] Add a test proving `proposed_use: route` records are excluded from eval/calibration.
- [ ] Document that public route-bank recall smoke is not quality evidence.

Verification:

```bash
uv run python -m pytest tests/test_build_semantic_assets.py tests/test_eval_routes.py -q
```

## Task 4: New-User Runtime Clarity

**Files:**
- Modify: `config/routes.yaml`
- Modify: `examples/intentmux-home/config/routes.yaml`
- Modify: `README.md`

- [ ] Add top comments to both `routes.yaml` files: built-in development default vs runtime template.
- [ ] Make `examples/intentmux-home/config/routes.yaml` the clearest place to edit `lite.target_model` and `deep.target_model`.
- [ ] Add a compact "first run" checklist before advanced docs in README.

Verification:

```bash
uv run python scripts/verify_route_contract.py
git diff --check
```

## Task 5: Regenerate Local Baseline Only After Tasks 1-4

**Files:**
- Generated ignored files only:
  - `data/semantic_sets/normalized/semantic_records.jsonl`
  - `data/semantic_sets/route_bank.yaml`
  - `data/semantic_sets/eval_bank.yaml`
  - `data/semantic_sets/calibration_bank.yaml`

- [ ] Run the builder locally.
- [ ] Inspect counts by `route`, `language`, `slice`, and `source`.
- [ ] Do not commit generated assets.
- [ ] Use the report to decide whether this baseline is good enough to deploy locally.

Verification:

```bash
uv sync --group assets
uv run python scripts/build_semantic_assets.py
uv run python -m pytest tests/test_build_semantic_assets.py tests/test_route_quality_report.py -q
```

## Task 6: Embedding Cache Plan Boundary

**Files:**
- Modify: `docs/router_data_pipeline_research.md`

- [ ] Keep cache out of this corpus-baseline change.
- [ ] Record next cache design: JSONL + manifest; cache route-bank utterance embeddings only.
- [ ] Explicitly defer SQLite until multi-process shared cache, large-scale query needs, or transaction requirements appear.

## Stop Conditions

Stop before implementation that would:

- commit generated route/eval/calibration assets;
- add zh-TW back into the default baseline;
- bulk-translate English datasets and call them Chinese quality evidence;
- use Retinue/OpenCode raw prompts as public examples;
- change production route thresholds before a before/after report exists;
- add SQLite/vector DB before measuring JSONL cache limits.
