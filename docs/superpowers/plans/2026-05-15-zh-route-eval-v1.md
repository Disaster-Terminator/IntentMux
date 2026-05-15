# zh-route-eval v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build IntentMux's first Chinese-first fast/strong routing quality baseline so route-bank changes can be judged by reproducible evals instead of local traffic guesses.

**Architecture:** Keep runtime unchanged. Add offline eval assets, source manifests, validation, and report metrics that map Chinese-native benchmark samples and curated review samples into IntentMux's two product routes: `fast` and `strong`. Use English router benchmarks for methodology only; do not bulk-translate them into the primary Chinese benchmark.

**Tech Stack:** Python 3.11, `uv`, PyYAML, existing `scripts/eval_routes.py`, `scripts/build_eval_bank.py`, `scripts/route_quality_report.py`, existing route config and route-bank tooling.

---

## Current Evidence

IntentMux already has route quality scaffolding:

- `docs/router_quality_research.md` defines the lightweight two-tier boundary.
- `config/route_sources.yaml` currently uses MASSIVE zh-CN / zh-TW for `fast`, and SWE-bench / MBPP / HumanEval for `strong`.
- `scripts/build_eval_bank.py` can merge manual cases and route-bank samples, but it has no slice-level labels or Chinese benchmark source policy.
- `scripts/route_quality_report.py` reports route quality, but not product metrics such as `strong_recall_high_risk` or `fast_precision_general`.

External research direction:

- RouterBench and LLMRouterBench are router methodology references, not Chinese route-label datasets.
- RouteLLM confirms the strong/weak model-pair framing and threshold/cost-quality evaluation pattern.
- CLUE, DataCLUE, MASSIVE, C-Eval, CMMLU, LongBench, SuperCLUE-Code3, and C-MTEB are Chinese benchmark assets, but they need IntentMux-specific `fast` / `strong` labels.

Decision:

- Primary benchmark data must be Chinese-native.
- Translated English benchmark samples are allowed only as a small coverage patch and comparison slice.
- The first tracked deliverable is a small public sample plus schema and metrics; full generated datasets remain untracked deployment assets unless explicitly curated.
- This is an eval baseline, not a route-bank replacement. Runtime routing and production route-bank promotion stay behind the existing rollout gate.

Retinue read-only cross-check agreed with the project boundary and flagged the main current gap: `strong` sources are still mostly English (`SWE-bench`, `MBPP`, `HumanEval`), while Chinese fast/general coverage already exists through MASSIVE zh-CN / zh-TW. The first execution pass should therefore prove Chinese strong/borderline evaluation before changing route-bank construction.

## MVP Cut

If execution time is limited, implement only these first:

1. `docs/zh_route_eval_plan.md` for public project direction.
2. `config/zh_route_eval_sources.yaml` for source/license policy.
3. `data/source_samples/zh_route_eval_v1.sample.yaml` with a tiny public schema sample.
4. `scripts/build_zh_route_eval.py` validation and sample build.
5. `slice_quality_metrics` in `scripts/route_quality_report.py`.

Do not change `config/routes.yaml`, production route bank, LiteLLM config, or runtime routing in the MVP.

## Target Eval Slices

`zh-intentmux-router-eval-v1` uses these slices:

| slice | route | target count v1 | source policy |
| --- | --- | ---: | --- |
| `fast_general_zh` | `fast` | 300 | MASSIVE zh, CLUE/DataCLUE short general utterances |
| `fast_intent_zh` | `fast` | 200 | DataCLUE CIC or similar Chinese intent data |
| `strong_code_zh` | `strong` | 250 | SuperCLUE-Code3, HumanEval-X/XL Chinese or small translated supplement |
| `strong_reasoning_zh` | `strong` | 200 | C-Eval, CMMLU, AGIEval/Gaokao-like Chinese reasoning |
| `strong_long_context_zh` | `strong` | 100 | LongBench Chinese tasks, sampled as request summaries |
| `high_risk_zh` | `strong` | 100 | curated public/manual + redacted production review samples |
| `borderline_zh` | manual | 200 | curated Chinese engineering boundary prompts |

Minimum quality gates for v1:

- `strong_recall_high_risk >= 0.98`
- `strong_recall_code >= 0.90`
- `fast_precision_general >= 0.90`
- `borderline_review_pass_rate >= 0.80`
- report must show `low_confidence_rate`, `near_margin_rate`, `hard_rule_hit_rate`, and `strong_call_rate`

## File Map

- Create `docs/zh_route_eval_plan.md`: public narrative, data-source policy, source/license matrix, and benchmark scope.
- Create `config/zh_route_eval_sources.yaml`: declarative source manifest for eval-bank construction.
- Create `data/source_samples/zh_route_eval_v1.sample.yaml`: tiny tracked sample showing slice schema without committing full generated data.
- Create `scripts/build_zh_route_eval.py`: offline builder that validates slice metadata and emits `data/semantic_sets/zh_route_eval_v1.yaml`.
- Modify `scripts/route_quality_report.py`: add slice-level route metrics.
- Modify `scripts/eval_routes.py` only if its current output cannot expose per-slice data to `route_quality_report.py`.
- Add tests under `tests/test_build_zh_route_eval.py` and `tests/test_route_quality_report.py`.
- Update `docs/router_quality_research.md` and `README.md` to point to the new eval baseline.

## Task 1: Public Research Plan And Source Policy

**Files:**
- Create: `docs/zh_route_eval_plan.md`
- Modify: `docs/router_quality_research.md`
- Modify: `README.md`

- [ ] **Step 1: Write the public plan document**

Create `docs/zh_route_eval_plan.md` with this structure:

```markdown
# Chinese Route Eval Plan

IntentMux does not try to become a general API gateway or a large router platform.
The next quality milestone is a Chinese-first fast/strong routing eval bank.

## Principle

- Chinese-native data is the primary benchmark source.
- English router benchmarks are methodology references.
- Translated English samples are at most a small supplement.
- Full generated eval banks are deployment assets unless curated for public release.

## Slices

| slice | expected route | source family |
| --- | --- | --- |
| fast_general_zh | fast | MASSIVE zh, CLUE/DataCLUE general text |
| fast_intent_zh | fast | DataCLUE CIC-like intent data |
| strong_code_zh | strong | SuperCLUE-Code3, HumanEval-X/XL supplement |
| strong_reasoning_zh | strong | C-Eval, CMMLU, AGIEval/Gaokao-like data |
| strong_long_context_zh | strong | LongBench Chinese |
| high_risk_zh | strong | curated public/manual and redacted production review |
| borderline_zh | manual | curated Chinese engineering boundary prompts |

## Metrics

- strong_recall_high_risk
- strong_recall_code
- fast_precision_general
- low_confidence_rate
- near_margin_rate
- hard_rule_hit_rate
- strong_call_rate
```

- [ ] **Step 2: Link it from existing docs**

Add one paragraph to `docs/router_quality_research.md` after "Current Source Set":

```markdown
The next eval milestone is `zh-intentmux-router-eval-v1`, described in
`docs/zh_route_eval_plan.md`. It uses Chinese-native datasets as the primary
source and borrows RouterBench / LLMRouterBench evaluation methodology without
bulk-translating English benchmarks into the main eval bank.
```

Add one sentence to README's route quality section:

```markdown
中文路由质量基线见 [docs/zh_route_eval_plan.md](docs/zh_route_eval_plan.md)。
```

- [ ] **Step 3: Verify documentation links**

Run:

```bash
uv run python scripts/preflight.py
```

Expected: existing preflight checks pass.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/router_quality_research.md docs/zh_route_eval_plan.md
git commit -m "docs: define Chinese route eval plan"
```

## Task 2: Eval Source Manifest

**Files:**
- Create: `config/zh_route_eval_sources.yaml`
- Test: `tests/test_build_zh_route_eval.py`

- [ ] **Step 1: Write failing manifest validation test**

Create `tests/test_build_zh_route_eval.py`:

```python
from __future__ import annotations

import pytest

from scripts.build_zh_route_eval import validate_source_manifest


def test_validate_source_manifest_requires_known_slices():
    manifest = {
        "sources": [
            {
                "name": "massive_zh_general",
                "slice": "fast_general_zh",
                "route": "fast",
                "kind": "huggingface",
                "homepage": "https://example.test",
                "license": "CC BY 4.0",
            }
        ]
    }

    validate_source_manifest(manifest)


def test_validate_source_manifest_rejects_unknown_slice():
    manifest = {
        "sources": [
            {
                "name": "bad",
                "slice": "misc",
                "route": "fast",
                "kind": "manual",
                "homepage": "https://example.test",
                "license": "unknown",
            }
        ]
    }

    with pytest.raises(ValueError, match="unknown slice"):
        validate_source_manifest(manifest)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_build_zh_route_eval.py -q
```

Expected: import error for `scripts.build_zh_route_eval`.

- [ ] **Step 3: Implement minimal validator**

Create `scripts/build_zh_route_eval.py`:

```python
from __future__ import annotations

from typing import Any

KNOWN_SLICES = {
    "fast_general_zh",
    "fast_intent_zh",
    "strong_code_zh",
    "strong_reasoning_zh",
    "strong_long_context_zh",
    "high_risk_zh",
    "borderline_zh",
}

KNOWN_ROUTES = {"fast", "strong", "manual"}


def validate_source_manifest(manifest: dict[str, Any]) -> None:
    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("sources must be a non-empty list")
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            raise ValueError(f"source #{index} must be an object")
        name = source.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError(f"source #{index} must set name")
        slice_name = source.get("slice")
        if slice_name not in KNOWN_SLICES:
            raise ValueError(f"source {name}: unknown slice {slice_name!r}")
        route = source.get("route")
        if route not in KNOWN_ROUTES:
            raise ValueError(f"source {name}: unknown route {route!r}")
        for key in ("kind", "homepage", "license"):
            if not isinstance(source.get(key), str) or not source[key]:
                raise ValueError(f"source {name}: missing {key}")
```

- [ ] **Step 4: Add the source manifest**

Create `config/zh_route_eval_sources.yaml`:

```yaml
sources:
  - name: massive_zh_general
    slice: fast_general_zh
    route: fast
    kind: remote_tar_jsonl
    homepage: https://www.amazon.science/code-and-datasets/massive
    license: CC BY 4.0
    notes: Chinese-native general assistant utterances.

  - name: dataclue_cic_intent
    slice: fast_intent_zh
    route: fast
    kind: manual_review_required
    homepage: https://github.com/CLUEbenchmark/DataCLUE
    license: dataset-specific
    notes: Use only license-compatible short intent samples.

  - name: ceval_reasoning
    slice: strong_reasoning_zh
    route: strong
    kind: manual_review_required
    homepage: https://cevalbenchmark.com/
    license: dataset-specific
    notes: Convert questions into user-request style prompts without answers.

  - name: cmmlu_reasoning
    slice: strong_reasoning_zh
    route: strong
    kind: manual_review_required
    homepage: https://github.com/haonan-li/CMMLU
    license: dataset-specific
    notes: Use for Chinese reasoning requests after license review.

  - name: longbench_zh
    slice: strong_long_context_zh
    route: strong
    kind: manual_review_required
    homepage: https://github.com/THUDM/LongBench
    license: dataset-specific
    notes: Convert into long-context request summaries without committing full contexts.

  - name: superclue_code3
    slice: strong_code_zh
    route: strong
    kind: manual_review_required
    homepage: https://github.com/CLUEbenchmark/SuperCLUE-Code3
    license: dataset-specific
    notes: Chinese-native code tasks.

  - name: curated_high_risk_zh
    slice: high_risk_zh
    route: strong
    kind: curated_yaml
    homepage: https://github.com/Disaster-Terminator/IntentMux
    license: Apache-2.0
    notes: Public/manual and redacted production-review prompts only.

  - name: curated_borderline_zh
    slice: borderline_zh
    route: manual
    kind: curated_yaml
    homepage: https://github.com/Disaster-Terminator/IntentMux
    license: Apache-2.0
    notes: Human-reviewed boundary prompts with explicit expected route.
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/test_build_zh_route_eval.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add config/zh_route_eval_sources.yaml scripts/build_zh_route_eval.py tests/test_build_zh_route_eval.py
git commit -m "eval: add Chinese route source manifest"
```

## Task 3: Public Sample Schema

**Files:**
- Create: `data/source_samples/zh_route_eval_v1.sample.yaml`
- Modify: `scripts/build_zh_route_eval.py`
- Test: `tests/test_build_zh_route_eval.py`

- [ ] **Step 1: Add failing sample loader test**

Append to `tests/test_build_zh_route_eval.py`:

```python
from pathlib import Path

from scripts.build_zh_route_eval import load_curated_samples


def test_load_curated_samples_preserves_slice_route_and_source(tmp_path: Path):
    sample = tmp_path / "samples.yaml"
    sample.write_text(
        """
samples:
  - id: borderline_001
    slice: borderline_zh
    text: 这个方案靠谱吗
    expect: strong
    source: curated_borderline_zh
    redacted: true
""",
        encoding="utf-8",
    )

    assert load_curated_samples(sample) == [
        {
            "id": "borderline_001",
            "slice": "borderline_zh",
            "text": "这个方案靠谱吗",
            "expect": "strong",
            "source": "curated_borderline_zh",
            "redacted": True,
        }
    ]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_build_zh_route_eval.py::test_load_curated_samples_preserves_slice_route_and_source -q
```

Expected: import error for `load_curated_samples`.

- [ ] **Step 3: Implement sample loader**

Add to `scripts/build_zh_route_eval.py`:

```python
from pathlib import Path

import yaml


def load_curated_samples(path: Path) -> list[dict[str, Any]]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    samples = payload.get("samples")
    if not isinstance(samples, list):
        raise ValueError("samples must be a list")
    validated: list[dict[str, Any]] = []
    for index, sample in enumerate(samples):
        if not isinstance(sample, dict):
            raise ValueError(f"sample #{index} must be an object")
        if sample.get("slice") not in KNOWN_SLICES:
            raise ValueError(f"sample #{index}: unknown slice {sample.get('slice')!r}")
        if sample.get("expect") not in {"fast", "strong"}:
            raise ValueError(f"sample #{index}: expect must be fast or strong")
        if sample.get("redacted") is not True:
            raise ValueError(f"sample #{index}: redacted must be true")
        for key in ("id", "text", "source"):
            if not isinstance(sample.get(key), str) or not sample[key]:
                raise ValueError(f"sample #{index}: missing {key}")
        validated.append(dict(sample))
    return validated
```

- [ ] **Step 4: Add tracked sample file**

Create `data/source_samples/zh_route_eval_v1.sample.yaml`:

```yaml
samples:
  - id: fast_general_001
    slice: fast_general_zh
    text: 帮我把这段话润色一下
    expect: fast
    source: curated_public_sample
    redacted: true

  - id: strong_code_001
    slice: strong_code_zh
    text: 这个 PR 会不会引入回归
    expect: strong
    source: curated_public_sample
    redacted: true

  - id: high_risk_001
    slice: high_risk_zh
    text: 线上服务偶发卡死，帮我定位根因
    expect: strong
    source: curated_public_sample
    redacted: true

  - id: borderline_001
    slice: borderline_zh
    text: 这个方案靠谱吗
    expect: strong
    source: curated_public_sample
    redacted: true
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/test_build_zh_route_eval.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add data/source_samples/zh_route_eval_v1.sample.yaml scripts/build_zh_route_eval.py tests/test_build_zh_route_eval.py
git commit -m "eval: add Chinese route sample schema"
```

## Task 4: Slice-Level Metrics

**Files:**
- Modify: `scripts/route_quality_report.py`
- Test: `tests/test_route_quality_report.py`

- [ ] **Step 1: Add failing metric test**

Add a test that calls a new function `slice_quality_metrics`:

```python
from scripts.route_quality_report import slice_quality_metrics


def test_slice_quality_metrics_reports_product_gates():
    cases = [
        {"id": "fast1", "slice": "fast_general_zh", "expect": "fast"},
        {"id": "risk1", "slice": "high_risk_zh", "expect": "strong"},
        {"id": "code1", "slice": "strong_code_zh", "expect": "strong"},
    ]
    decisions = {
        "fast1": {"route_id": "fast", "reason": "embedding"},
        "risk1": {"route_id": "strong", "reason": "hard_rule:越权"},
        "code1": {"route_id": "fast", "reason": "low_confidence"},
    }

    metrics = slice_quality_metrics(cases, decisions)

    assert metrics["fast_precision_general"] == 1.0
    assert metrics["strong_recall_high_risk"] == 1.0
    assert metrics["strong_recall_code"] == 0.0
    assert metrics["low_confidence_rate"] == 1 / 3
    assert metrics["strong_call_rate"] == 1 / 3
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_route_quality_report.py::test_slice_quality_metrics_reports_product_gates -q
```

Expected: import error or missing function failure.

- [ ] **Step 3: Implement metrics**

Add `slice_quality_metrics(cases, decisions)` in `scripts/route_quality_report.py` using exact route ids:

```python
def slice_quality_metrics(
    cases: list[dict[str, str]],
    decisions: dict[str, dict[str, object]],
) -> dict[str, float]:
    def fraction(selected: list[bool]) -> float:
        return sum(1 for value in selected if value) / len(selected) if selected else 0.0

    fast_general = [
        decisions[case["id"]].get("route_id") == "fast"
        for case in cases
        if case.get("slice") == "fast_general_zh" and case["id"] in decisions
    ]
    high_risk = [
        decisions[case["id"]].get("route_id") == "strong"
        for case in cases
        if case.get("slice") == "high_risk_zh" and case["id"] in decisions
    ]
    code = [
        decisions[case["id"]].get("route_id") == "strong"
        for case in cases
        if case.get("slice") == "strong_code_zh" and case["id"] in decisions
    ]
    all_decisions = [decision for case_id, decision in decisions.items()]
    return {
        "fast_precision_general": fraction(fast_general),
        "strong_recall_high_risk": fraction(high_risk),
        "strong_recall_code": fraction(code),
        "low_confidence_rate": fraction(
            [decision.get("reason") == "low_confidence" for decision in all_decisions]
        ),
        "strong_call_rate": fraction(
            [decision.get("route_id") == "strong" for decision in all_decisions]
        ),
    }
```

- [ ] **Step 4: Run test**

```bash
uv run pytest tests/test_route_quality_report.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/route_quality_report.py tests/test_route_quality_report.py
git commit -m "report: add Chinese route slice metrics"
```

## Task 5: Builder CLI And End-To-End Sample Report

**Files:**
- Modify: `scripts/build_zh_route_eval.py`
- Modify: `docs/zh_route_eval_plan.md`
- Test: `tests/test_build_zh_route_eval.py`

- [ ] **Step 1: Add failing CLI test**

Add a subprocess test that writes a sample file and expects an output YAML:

```python
import json
import subprocess
import sys


def test_build_zh_route_eval_cli_writes_eval_yaml(tmp_path: Path):
    sample = tmp_path / "samples.yaml"
    output = tmp_path / "eval.yaml"
    sample.write_text(
        """
samples:
  - id: fast_001
    slice: fast_general_zh
    text: 帮我总结这段话
    expect: fast
    source: curated
    redacted: true
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/build_zh_route_eval.py",
            "--curated-samples",
            str(sample),
            "--output",
            str(output),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "wrote" in result.stdout
    assert "fast_001" in output.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_build_zh_route_eval.py::test_build_zh_route_eval_cli_writes_eval_yaml -q
```

Expected: CLI not implemented.

- [ ] **Step 3: Implement CLI**

Add `main()` to `scripts/build_zh_route_eval.py`:

```python
import argparse


def build_eval_payload(samples: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": "zh-intentmux-router-eval-v1",
        "cases": [
            {
                "id": sample["id"],
                "slice": sample["slice"],
                "text": sample["text"],
                "expect": sample["expect"],
                "source": sample["source"],
            }
            for sample in samples
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--curated-samples", action="append", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    samples: list[dict[str, Any]] = []
    for path in args.curated_samples:
        samples.extend(load_curated_samples(Path(path)))
    payload = build_eval_payload(samples)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print(f"wrote {output} with {len(payload['cases'])} cases")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run sample build**

```bash
uv run python scripts/build_zh_route_eval.py \
  --curated-samples data/source_samples/zh_route_eval_v1.sample.yaml \
  --output /tmp/zh_route_eval_v1.sample.yaml
```

Expected: writes `/tmp/zh_route_eval_v1.sample.yaml` with 4 cases.

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/test_build_zh_route_eval.py tests/test_route_quality_report.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/build_zh_route_eval.py tests/test_build_zh_route_eval.py docs/zh_route_eval_plan.md
git commit -m "eval: build Chinese route eval samples"
```

## Task 6: Verification And Production Safety

**Files:**
- No production config edits.
- No LiteLLM config edits.

- [ ] **Step 1: Run full tests**

```bash
uv run pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Run route contract verification**

```bash
uv run python scripts/verify_route_contract.py
```

Expected: `Route contract verification passed.`

- [ ] **Step 3: Run sample eval builder**

```bash
uv run python scripts/build_zh_route_eval.py \
  --curated-samples data/source_samples/zh_route_eval_v1.sample.yaml \
  --output /tmp/zh_route_eval_v1.sample.yaml
```

Expected: command exits 0 and prints case count.

- [ ] **Step 4: Confirm runtime unaffected**

```bash
curl -fsS http://127.0.0.1:4001/ready
```

Expected: JSON has `"ready": true`.

- [ ] **Step 5: Commit final docs if needed**

```bash
git status --short
git add README.md docs/zh_route_eval_plan.md docs/router_quality_research.md
git commit -m "docs: document Chinese route eval baseline"
```

Skip commit if `git status --short` is clean.

## Out Of Scope For This Plan

- No runtime route-policy change.
- No LLM arbiter.
- No bulk translation of RouterBench / LLMRouterBench.
- No generated full dataset committed to git.
- No production LiteLLM or container changes.

## Open Risks

- Some Chinese benchmark licenses may not allow redistribution. The manifest must track license and generated full banks must stay untracked until reviewed.
- Public Chinese code-agent datasets may not map cleanly to "user request should use strong". Human review is required for sample conversion.
- `borderline_zh` is the product-defining slice and cannot be solved by public datasets alone; it needs curated public samples plus redacted production review samples.
- Strong/fast labels are product policy, not universal truth. Reports should show slice metrics instead of pretending there is one global accuracy.
