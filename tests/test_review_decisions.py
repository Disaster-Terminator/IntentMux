from __future__ import annotations

import json

from pathlib import Path

import pytest

from scripts import review_decisions
from scripts.review_decisions import DEFAULT_ROUTE_MODEL, format_result_row, load_cases, run_review


def test_load_cases_from_yaml_supports_text_and_messages(tmp_path):
    path = tmp_path / "cases.yaml"
    path.write_text(
        """
cases:
  - name: text case
    text: hello
    expected_target: cheap-router
  - name: messages case
    messages:
      - role: user
        content: hi
""",
        encoding="utf-8",
    )

    cases = load_cases(path)

    assert [case.name for case in cases] == ["text case", "messages case"]
    assert cases[0].payload == {
        "model": DEFAULT_ROUTE_MODEL,
        "messages": [{"role": "user", "content": "hello"}],
    }
    assert cases[0].expected_target == "cheap-router"
    assert cases[1].payload == {
        "model": DEFAULT_ROUTE_MODEL,
        "messages": [{"role": "user", "content": "hi"}],
    }
    assert cases[1].expected_target is None


def test_load_cases_from_jsonl(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"name": "a", "text": "hello", "expected_target": "cheap-router"}),
                json.dumps(
                    {
                        "name": "b",
                        "messages": [{"role": "user", "content": "hi"}],
                        "model": "custom-router",
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    cases = load_cases(path)

    assert cases[0].payload == {
        "model": DEFAULT_ROUTE_MODEL,
        "messages": [{"role": "user", "content": "hello"}],
    }
    assert cases[1].payload == {
        "messages": [{"role": "user", "content": "hi"}],
        "model": "custom-router",
    }


def test_format_result_row_supports_pass_fail_and_na():
    assert format_result_row(
        case_name="match",
        target_model="pro-router",
        expected_target="pro-router",
        reason="hard_rule:线上",
    ) == ["PASS", "match", "pro-router", "pro-router", "hard_rule:线上"]
    assert format_result_row(
        case_name="mismatch",
        target_model="cheap-router",
        expected_target="pro-router",
        reason="semantic_similarity",
    )[0] == "FAIL"
    assert format_result_row(
        case_name="no-expected",
        target_model="cheap-router",
        expected_target=None,
        reason="semantic_similarity",
    )[0] == "N/A"


def test_run_review_default_table_output(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path):
    path = tmp_path / "cases.yaml"
    path.write_text(
        """
cases:
  - name: table-case
    text: hi
    expected_target: cheap-router
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        review_decisions,
        "call_decision_endpoint",
        lambda endpoint, payload, timeout: {"target_model": "cheap-router", "reason": "semantic_similarity"},
    )

    rc = run_review("http://example.com", path, 1.0)
    out = capsys.readouterr().out
    assert rc == 0
    assert "status" in out
    assert "PASS" in out
    assert "Total cases: 1; mismatches: 0" in out


def test_run_review_json_output_shape(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path):
    path = tmp_path / "cases.yaml"
    path.write_text(
        """
cases:
  - name: expected-pass
    text: hi
    expected_target: cheap-router
  - name: no-expected
    text: hello
""",
        encoding="utf-8",
    )
    results = iter(
        [
            {"target_model": "cheap-router", "reason": "hard_rule", "scores": {"cheap-router": 0.8}},
            {"target_model": "pro-router", "reason": "semantic_similarity"},
        ]
    )
    monkeypatch.setattr(review_decisions, "call_decision_endpoint", lambda endpoint, payload, timeout: next(results))

    rc = run_review("http://example.com", path, 1.0, output="json")
    out = capsys.readouterr().out
    parsed = json.loads(out)

    assert rc == 0
    assert isinstance(parsed, list)
    assert parsed[0] == {
        "case_name": "expected-pass",
        "expected_target": "cheap-router",
        "actual_target": "cheap-router",
        "status": "pass",
        "reason": "hard_rule",
        "request_model": DEFAULT_ROUTE_MODEL,
        "scores": {"cheap-router": 0.8},
    }
    assert parsed[1]["status"] is None
    assert parsed[1]["expected_target"] is None


def test_run_review_mismatch_exits_nonzero(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    path = tmp_path / "cases.yaml"
    path.write_text(
        """
cases:
  - name: mismatch
    text: hi
    expected_target: cheap-router
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        review_decisions,
        "call_decision_endpoint",
        lambda endpoint, payload, timeout: {"target_model": "pro-router", "reason": "semantic_similarity"},
    )

    rc = run_review("http://example.com", path, 1.0, output="json")
    assert rc == 1
