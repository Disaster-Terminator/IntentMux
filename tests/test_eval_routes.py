from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.eval_routes import EvalCase, load_cases, validate_case_route_ids


def test_validate_case_route_ids_accepts_known_route_id():
    validate_case_route_ids([EvalCase(text="hi", expect="fast")], {"fast", "strong"})


def test_validate_case_route_ids_rejects_target_model_name():
    with pytest.raises(ValueError, match="pro-router"):
        validate_case_route_ids([EvalCase(text="hi", expect="pro-router")], {"fast", "strong"})


def test_load_cases_ignores_eval_builder_metadata(tmp_path: Path):
    cases = tmp_path / "cases.yaml"
    cases.write_text(
        """
cases:
  - id: fast_001
    slice: fast_general_zh
    text: 帮我总结这段话
    expect: fast
    source: curated
    rationale: 普通总结请求低风险，适合 fast。
""",
        encoding="utf-8",
    )

    assert load_cases(cases) == [
        EvalCase(
            id="fast_001",
            slice="fast_general_zh",
            text="帮我总结这段话",
            expect="fast",
            source="curated",
        )
    ]


def test_load_cases_preserves_long_context_metadata(tmp_path: Path):
    cases = tmp_path / "cases.yaml"
    cases.write_text(
        """
cases:
  - id: long_001
    slice: strong_long_context_zh
    text: 请基于长文档定位冲突结论
    expect: strong
    source: curated
    input_chars: 12000
    message_count: 3
    context_policy: preserved_length
""",
        encoding="utf-8",
    )

    assert load_cases(cases) == [
        EvalCase(
            id="long_001",
            slice="strong_long_context_zh",
            text="请基于长文档定位冲突结论",
            expect="strong",
            source="curated",
            input_chars=12000,
            message_count=3,
            context_policy="preserved_length",
        )
    ]


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


def test_eval_routes_json_output_preserves_long_context_metadata(tmp_path: Path):
    cases = tmp_path / "cases.yaml"
    output = tmp_path / "eval.json"
    cases.write_text(
        """
cases:
  - id: long_001
    slice: strong_long_context_zh
    text: 线上长文档分析是否存在数据损坏风险
    expect: strong
    source: test
    input_chars: 12000
    message_count: 3
    context_policy: preserved_length
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

    case = json.loads(output.read_text(encoding="utf-8"))["cases"][0]
    assert case["slice"] == "strong_long_context_zh"
    assert case["input_chars"] == 12000
    assert case["message_count"] == 3
    assert case["context_policy"] == "preserved_length"


def test_mock_eval_keeps_generic_advice_on_fast(tmp_path: Path):
    cases = tmp_path / "cases.yaml"
    output = tmp_path / "eval.json"
    cases.write_text(
        """
cases:
  - id: fast_general_advice_001
    slice: fast_general_zh
    text: 这个学习计划靠谱吗？
    expect: fast
    source: regression
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

    case = json.loads(output.read_text(encoding="utf-8"))["cases"][0]
    assert case["actual_route"] == "fast"
