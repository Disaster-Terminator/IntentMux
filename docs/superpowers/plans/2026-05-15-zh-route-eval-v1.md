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
- `scripts/route_quality_report.py` reports route quality, but not product metrics such as `strong_recall_high_risk` or `fast_general_keep_rate`.

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
4. `scripts/eval_routes.py --json-output` with `id`, `slice`, decision details, and backward-compatible stdout.
5. `scripts/route_quality_report.py` consuming eval JSON and producing real slice/product metrics.
6. `scripts/build_zh_route_eval.py` validation and sample build.

Do not change `config/routes.yaml`, production route bank, LiteLLM config, or runtime routing in the MVP.

## Review Corrections

The first review of this plan found one blocking engineering gap: the original
Task 4 tried to add `slice_quality_metrics(cases, decisions)` before the real
eval pipeline had `id`, `slice`, or JSON decision output. That would produce a
unit-test-only metric with no connection to actual `scripts/eval_routes.py`
runs. The corrected dependency chain is:

```text
sample schema with id/slice/expect
  -> eval_routes.py JSON output
  -> route_quality_report.py reads eval JSON
  -> slice_metrics and product_metrics
```

Additional corrections:

- `borderline_zh` is not a route. It uses `label_policy:
  manual_review_required`; every executable sample still ends with
  `expect: fast` or `expect: strong`.
- `fast_precision_general` was imprecise. Use `fast_general_keep_rate` for
  the rate of `fast_general_zh` retained on `fast`, and `fast_precision` for
  the precision of all actual `fast` decisions.
- `near_margin_rate` requires `score`, `second_score`, and configured margin.
  If any required value is unavailable, report `null` instead of pretending the
  metric was measured.
- Source manifests must use explicit license metadata. Avoid
  `license: dataset-specific`; use `license_id`, `license_url`,
  `redistributable`, `commercial_use`, `derived_prompt_allowed`, and
  `commit_policy`.
- Long-context samples should preserve length evidence through metadata such as
  `input_chars`, `message_count`, and `context_policy`. If only summaries are
  available, keep `strong_long_context_zh` as schema-reserved rather than
  claiming it is measured.

## Target Eval Slices

`zh-intentmux-router-eval-v1` uses these slices:

| slice | expected route | target count v1 | source policy |
| --- | --- | ---: | --- |
| `fast_general_zh` | `fast` | 300 | MASSIVE zh, CLUE/DataCLUE short general utterances |
| `fast_intent_zh` | `fast` | 200 | DataCLUE CIC or similar Chinese intent data |
| `strong_code_zh` | `strong` | 250 | SuperCLUE-Code3, HumanEval-X/XL Chinese or small translated supplement |
| `strong_reasoning_zh` | `strong` | 200 | C-Eval, CMMLU, AGIEval/Gaokao-like Chinese reasoning |
| `strong_long_context_zh` | `strong` | 100 | LongBench Chinese tasks with length metadata, or schema-reserved until length evidence is preserved |
| `high_risk_zh` | `strong` | 100 | curated public/manual + redacted production review samples |
| `borderline_zh` | reviewed `fast` or `strong` | 200 | curated Chinese engineering boundary prompts with `label_policy: manual_review_required` |

Minimum quality gates for v1:

- `strong_recall_high_risk >= 0.98`
- `strong_recall_code >= 0.90`
- `fast_general_keep_rate >= 0.90`
- `fast_precision >= 0.90`
- `borderline_review_pass_rate >= 0.80`
- report must show `low_confidence_rate`, `near_margin_rate`, `hard_rule_hit_rate`, and `strong_call_rate`

## File Map

- Create `docs/zh_route_eval_plan.md`: public narrative, data-source policy, source/license matrix, and benchmark scope.
- Create `config/zh_route_eval_sources.yaml`: declarative source manifest for eval-bank construction.
- Create `data/source_samples/zh_route_eval_v1.sample.yaml`: tiny tracked sample showing slice schema without committing full generated data.
- Create `scripts/build_zh_route_eval.py`: offline builder that validates slice metadata and emits `data/semantic_sets/zh_route_eval_v1.yaml`.
- Modify `scripts/eval_routes.py`: add `id`, `slice`, optional structural metadata, and `--json-output`.
- Modify `scripts/route_quality_report.py`: read eval JSON and add slice-level route metrics.
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
| borderline_zh | reviewed fast or strong | curated Chinese engineering boundary prompts |

## Metrics

- strong_recall_high_risk
- strong_recall_code
- fast_general_keep_rate
- fast_precision
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
                "license_id": "CC-BY-4.0",
                "license_url": "https://example.test/license",
                "redistributable": True,
                "commercial_use": True,
                "derived_prompt_allowed": "yes",
                "commit_policy": "sample_only",
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
                "license_id": "unknown",
                "license_url": "https://example.test/license",
                "redistributable": False,
                "commercial_use": False,
                "derived_prompt_allowed": "review_required",
                "commit_policy": "manifest_only",
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

KNOWN_ROUTES = {"fast", "strong"}


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
        for key in (
            "kind",
            "homepage",
            "license_id",
            "license_url",
            "redistributable",
            "commercial_use",
            "derived_prompt_allowed",
            "commit_policy",
        ):
            if key in {"redistributable", "commercial_use"}:
                if not isinstance(source.get(key), bool):
                    raise ValueError(f"source {name}: missing {key}")
                continue
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
    license_id: CC-BY-4.0
    license_url: https://github.com/alexa/massive/blob/master/LICENSE
    redistributable: true
    commercial_use: true
    derived_prompt_allowed: yes
    commit_policy: sample_only
    notes: Chinese-native general assistant utterances.

  - name: dataclue_cic_intent
    slice: fast_intent_zh
    route: fast
    kind: manual_review_required
    homepage: https://github.com/CLUEbenchmark/DataCLUE
    license_id: review-required
    license_url: https://github.com/CLUEbenchmark/DataCLUE
    redistributable: false
    commercial_use: false
    derived_prompt_allowed: review_required
    commit_policy: manifest_only
    notes: Use only license-compatible short intent samples.

  - name: ceval_reasoning
    slice: strong_reasoning_zh
    route: strong
    kind: manual_review_required
    homepage: https://cevalbenchmark.com/
    license_id: CC-BY-NC-SA-4.0
    license_url: https://creativecommons.org/licenses/by-nc-sa/4.0/
    redistributable: false
    commercial_use: false
    derived_prompt_allowed: review_required
    commit_policy: manifest_only
    notes: Convert questions into user-request style prompts without answers.

  - name: cmmlu_reasoning
    slice: strong_reasoning_zh
    route: strong
    kind: manual_review_required
    homepage: https://github.com/haonan-li/CMMLU
    license_id: CC-BY-NC-SA-4.0
    license_url: https://creativecommons.org/licenses/by-nc-sa/4.0/
    redistributable: false
    commercial_use: false
    derived_prompt_allowed: review_required
    commit_policy: manifest_only
    notes: Use for Chinese reasoning requests after license review.

  - name: longbench_zh
    slice: strong_long_context_zh
    route: strong
    kind: manual_review_required
    homepage: https://github.com/THUDM/LongBench
    license_id: review-required
    license_url: https://github.com/THUDM/LongBench
    redistributable: false
    commercial_use: false
    derived_prompt_allowed: review_required
    commit_policy: manifest_only
    notes: Preserve length metadata or keep this slice schema-reserved.

  - name: superclue_code3
    slice: strong_code_zh
    route: strong
    kind: manual_review_required
    homepage: https://github.com/CLUEbenchmark/SuperCLUE-Code3
    license_id: review-required
    license_url: https://github.com/CLUEbenchmark/SuperCLUE-Code3
    redistributable: false
    commercial_use: false
    derived_prompt_allowed: review_required
    commit_policy: manifest_only
    notes: Chinese-native code tasks.

  - name: curated_high_risk_zh
    slice: high_risk_zh
    route: strong
    kind: curated_yaml
    homepage: https://github.com/Disaster-Terminator/IntentMux
    license_id: Apache-2.0
    license_url: https://www.apache.org/licenses/LICENSE-2.0
    redistributable: true
    commercial_use: true
    derived_prompt_allowed: yes
    commit_policy: sample_only
    notes: Public/manual and redacted production-review prompts only.

  - name: curated_borderline_zh
    slice: borderline_zh
    route: strong
    label_policy: manual_review_required
    kind: curated_yaml
    homepage: https://github.com/Disaster-Terminator/IntentMux
    license_id: Apache-2.0
    license_url: https://www.apache.org/licenses/LICENSE-2.0
    redistributable: true
    commercial_use: true
    derived_prompt_allowed: yes
    commit_policy: sample_only
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
    text: 这个网关方案会不会导致上下文泄漏、路由回归或成本失控？
    expect: strong
    source: curated_borderline_zh
    label_policy: manual_review_required
    rationale: 工程风险、隐私和成本回归需要强模型复核。
    redacted: true
""",
        encoding="utf-8",
    )

    assert load_curated_samples(sample) == [
        {
            "id": "borderline_001",
            "slice": "borderline_zh",
            "text": "这个网关方案会不会导致上下文泄漏、路由回归或成本失控？",
            "expect": "strong",
            "source": "curated_borderline_zh",
            "label_policy": "manual_review_required",
            "rationale": "工程风险、隐私和成本回归需要强模型复核。",
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
        for key in ("id", "text", "source", "rationale"):
            if not isinstance(sample.get(key), str) or not sample[key]:
                raise ValueError(f"sample #{index}: missing {key}")
        if sample.get("slice") == "borderline_zh" and sample.get("label_policy") != "manual_review_required":
            raise ValueError(f"sample #{index}: borderline_zh requires manual_review_required")
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
    rationale: 普通改写请求低风险，适合 fast。
    redacted: true

  - id: strong_code_001
    slice: strong_code_zh
    text: 这个 PR 会不会引入回归
    expect: strong
    source: curated_public_sample
    rationale: PR 回归分析需要代码风险判断，适合 strong。
    redacted: true

  - id: high_risk_001
    slice: high_risk_zh
    text: 线上服务偶发卡死，帮我定位根因
    expect: strong
    source: curated_public_sample
    rationale: 生产事故根因分析属于高风险任务，适合 strong。
    redacted: true

  - id: borderline_001
    slice: borderline_zh
    text: 这个网关方案会不会导致上下文泄漏、路由回归或成本失控？
    expect: strong
    source: curated_public_sample
    label_policy: manual_review_required
    rationale: 工程风险、隐私和成本回归需要强模型复核。
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

## Task 4: Eval JSON Output

**Files:**
- Modify: `scripts/eval_routes.py`
- Test: `tests/test_eval_routes.py`

- [ ] **Step 1: Add failing JSON output test**

Add to `tests/test_eval_routes.py`:

```python
import json
import subprocess
import sys
from pathlib import Path


def test_eval_routes_json_output_includes_id_slice_and_scores(tmp_path: Path):
    cases = tmp_path / "cases.yaml"
    output = tmp_path / "eval.json"
    cases.write_text(
        """
cases:
  - id: strong_code_001
    slice: strong_code_zh
    text: 这个 PR 会不会引入回归
    expect: strong
    source: test
""",
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            "scripts/eval_routes.py",
            "--cases",
            str(cases),
            "--mock-embeddings",
            "--json-output",
            str(output),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema"] == "intentmux-route-eval-v1"
    assert payload["cases"][0]["id"] == "strong_code_001"
    assert payload["cases"][0]["slice"] == "strong_code_zh"
    assert payload["cases"][0]["expect"] == "strong"
    assert payload["cases"][0]["actual_route"] == "strong"
    assert payload["cases"][0]["passed"] is True
    assert "score" in payload["cases"][0]
    assert "second_score" in payload["cases"][0]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_eval_routes.py::test_eval_routes_json_output_includes_id_slice_and_scores -q
```

Expected: CLI rejects `--json-output` or JSON file is missing.

- [ ] **Step 3: Implement JSON output**

Modify `scripts/eval_routes.py`:

```python
@dataclass(frozen=True)
class EvalCase:
    text: str
    expect: str
    source: str = "unknown"
    id: str | None = None
    slice: str | None = None


def case_id(case: EvalCase, index: int) -> str:
    return case.id or f"case_{index:04d}"
```

Inside `run_eval`, collect per-case records:

```python
results.append(
    {
        "id": case_id(case, index),
        "slice": case.slice,
        "text": case.text,
        "expect": case.expect,
        "actual_route": actual_route,
        "target_model": decision.target_model,
        "reason": decision.reason,
        "passed": actual_route == case.expect,
        "score": decision.score,
        "second_score": decision.second_score,
    }
)
```

Add CLI option:

```python
parser.add_argument("--json-output")
```

Write:

```python
if json_output:
    Path(json_output).write_text(
        json.dumps({"schema": "intentmux-route-eval-v1", "cases": results}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_eval_routes.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/eval_routes.py tests/test_eval_routes.py
git commit -m "eval: emit route eval JSON"
```

## Task 5: Slice Metrics From Eval JSON

**Files:**
- Modify: `scripts/route_quality_report.py`
- Test: `tests/test_route_quality_report.py`

- [ ] **Step 1: Add failing report test**

Add to `tests/test_route_quality_report.py`:

```python
from scripts.route_quality_report import build_quality_report_from_eval_json


def test_quality_report_reads_eval_json_and_reports_slice_metrics():
    eval_json = {
        "schema": "intentmux-route-eval-v1",
        "cases": [
            {"id": "fast1", "slice": "fast_general_zh", "expect": "fast", "actual_route": "fast", "reason": "embedding", "passed": True},
            {"id": "risk1", "slice": "high_risk_zh", "expect": "strong", "actual_route": "strong", "reason": "hard_rule:越权", "passed": True},
            {"id": "code1", "slice": "strong_code_zh", "expect": "strong", "actual_route": "fast", "reason": "low_confidence", "passed": False, "score": 0.54, "second_score": 0.52},
        ],
    }

    report = build_quality_report_from_eval_json(
        eval_json=eval_json,
        route_summary=None,
        route_bank_path="sample",
        margin=0.04,
    )

    assert report["product_metrics"]["fast_general_keep_rate"] == 1.0
    assert report["product_metrics"]["fast_precision"] == 0.5
    assert report["product_metrics"]["strong_recall_high_risk"] == 1.0
    assert report["product_metrics"]["strong_recall_code"] == 0.0
    assert report["product_metrics"]["low_confidence_rate"] == 1 / 3
    assert report["product_metrics"]["hard_rule_hit_rate"] == 1 / 3
    assert report["product_metrics"]["strong_call_rate"] == 1 / 3
    assert report["product_metrics"]["near_margin_rate"] == 1 / 3
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_route_quality_report.py::test_quality_report_reads_eval_json_and_reports_slice_metrics -q
```

Expected: import error or missing function failure.

- [ ] **Step 3: Implement JSON report path**

Add `build_quality_report_from_eval_json(...)` to `scripts/route_quality_report.py`.
It must compute:

- `slice_metrics` keyed by slice name.
- `product_metrics.fast_general_keep_rate`.
- `product_metrics.fast_precision`.
- `product_metrics.strong_recall_high_risk`.
- `product_metrics.strong_recall_code`.
- `product_metrics.low_confidence_rate`.
- `product_metrics.hard_rule_hit_rate`.
- `product_metrics.strong_call_rate`.
- `product_metrics.near_margin_rate`, or `None` when score/margin data is unavailable.
- `missing_decision_count`.

Keep the existing stdout parser for backward compatibility, but prefer eval JSON when a JSON input is provided.
Add CLI option:

```python
parser.add_argument("--eval-json", help="JSON output from scripts/eval_routes.py --json-output")
```

When `--eval-json` is present, load that file and call
`build_quality_report_from_eval_json(...)`. Keep `--eval-output` for existing
TSV reports.

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_route_quality_report.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/route_quality_report.py tests/test_route_quality_report.py
git commit -m "report: add Chinese route slice metrics"
```

## Task 6: Builder CLI And End-To-End Sample Report

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
    rationale: 普通总结请求低风险，适合 fast。
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
                "rationale": sample["rationale"],
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

## Task 7: Verification And Production Safety

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

- [ ] **Step 4: Run sample eval JSON**

```bash
uv run python scripts/eval_routes.py \
  --cases /tmp/zh_route_eval_v1.sample.yaml \
  --mock-embeddings \
  --json-output /tmp/zh_route_eval_v1.results.json
```

Expected: command exits 0 and writes JSON with `schema: intentmux-route-eval-v1`.

- [ ] **Step 5: Run quality report from eval JSON**

```bash
uv run python scripts/route_quality_report.py \
  --eval-json /tmp/zh_route_eval_v1.results.json \
  --route-bank examples/route_bank.sample.yaml \
  --json-output /tmp/zh_route_quality.json \
  --markdown-output /tmp/zh_route_quality.md
```

Expected: JSON contains `slice_metrics`, `product_metrics`, and `missing_decision_count`.

- [ ] **Step 6: Confirm runtime unaffected**

```bash
curl -fsS http://127.0.0.1:4001/ready
```

Expected: JSON has `"ready": true`.

- [ ] **Step 7: Commit final docs if needed**

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
