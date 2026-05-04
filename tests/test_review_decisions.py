from __future__ import annotations

import json

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


def test_run_review_default_table_output_and_success_exit(monkeypatch, tmp_path, capsys):
    path = tmp_path / "cases.yaml"
    path.write_text(
        """
cases:
  - name: expects match
    text: hello
    expected_target: cheap-router
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        review_decisions,
        "call_decision_endpoint",
        lambda endpoint, payload, timeout_s: {"target_model": "cheap-router", "reason": "semantic_similarity"},
    )

    exit_code = run_review("http://localhost", path, 1.0)
    output = capsys.readouterr().out
    assert exit_code == 0
    assert "status" in output
    assert "PASS" in output
    assert "Total cases: 1; mismatches: 0" in output


def test_run_review_json_output_shape_and_neutral_status(monkeypatch, tmp_path, capsys):
    path = tmp_path / "cases.yaml"
    path.write_text(
        """
cases:
  - name: expected match
    text: hello
    expected_target: cheap-router
  - name: no expectation
    text: hi
""",
        encoding="utf-8",
    )

    responses = iter(
        [
            {"target_model": "cheap-router", "reason": "semantic_similarity", "score": 0.88},
            {"target_model": "pro-router", "reason": "semantic_similarity", "scores": {"cheap-router": 0.2}},
        ]
    )
    monkeypatch.setattr(review_decisions, "call_decision_endpoint", lambda *_args: next(responses))

    exit_code = run_review("http://localhost", path, 1.0, output="json")
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output[0] == {
        "case": "expected match",
        "expected_target": "cheap-router",
        "actual_target": "cheap-router",
        "status": "pass",
        "reason": "semantic_similarity",
        "request_payload_model": DEFAULT_ROUTE_MODEL,
        "score": 0.88,
    }
    assert output[1]["case"] == "no expectation"
    assert output[1]["expected_target"] is None
    assert output[1]["status"] is None
    assert output[1]["scores"] == {"cheap-router": 0.2}


def test_run_review_mismatch_expected_route_exits_nonzero(monkeypatch, tmp_path):
    path = tmp_path / "cases.yaml"
    path.write_text(
        """
cases:
  - name: mismatch
    text: hello
    expected_target: cheap-router
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        review_decisions,
        "call_decision_endpoint",
        lambda *_args: {"target_model": "pro-router", "reason": "semantic_similarity"},
    )

    assert run_review("http://localhost", path, 1.0, output="json") == 1
