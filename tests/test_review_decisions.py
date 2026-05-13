from __future__ import annotations

import json

import pytest

from scripts import review_decisions
from scripts.review_decisions import (
    DEFAULT_ROUTE_MODEL,
    format_result_row,
    load_cases,
    main,
    run_review,
    validate_expected_routes,
)
from scripts.import_review_samples import convert_review_samples


def test_load_cases_from_yaml_supports_text_and_messages(tmp_path):
    path = tmp_path / "cases.yaml"
    path.write_text(
        """
cases:
  - name: text case
    text: hello
    expected_route: fast
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
    assert cases[0].expected_route == "fast"
    assert cases[1].payload == {
        "model": DEFAULT_ROUTE_MODEL,
        "messages": [{"role": "user", "content": "hi"}],
    }
    assert cases[1].expected_route is None


def test_load_cases_from_jsonl(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"name": "a", "text": "hello", "expected_route": "fast"}),
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


def test_load_cases_accepts_imported_review_samples_without_name(tmp_path):
    imported = convert_review_samples(
        [
            json.dumps(
                {
                    "redacted": True,
                    "text": "帮我分析这个 PR 的回归风险",
                    "expect": "strong",
                    "source": "manual_review",
                },
                ensure_ascii=False,
            )
        ],
        allowed_route_ids={"fast", "strong"},
    )
    path = tmp_path / "imported.yaml"
    import yaml

    path.write_text(yaml.safe_dump(imported, allow_unicode=True, sort_keys=False), encoding="utf-8")

    cases = load_cases(path)

    assert cases[0].name == "production_review:manual_review#0001"
    assert cases[0].payload == {
        "model": DEFAULT_ROUTE_MODEL,
        "messages": [{"role": "user", "content": "帮我分析这个 PR 的回归风险"}],
    }
    assert cases[0].expected_route == "strong"


def test_review_decisions_default_endpoint_matches_project_port(monkeypatch):
    captured: dict[str, object] = {}

    def fake_run_review(endpoint, cases_path, timeout_s, *, routes_path=None, output="table"):
        captured["endpoint"] = endpoint
        captured["cases_path"] = cases_path
        return 0

    monkeypatch.setattr(review_decisions, "run_review", fake_run_review)

    assert main(["--cases", "tests/samples/review_decisions.yaml"]) == 0
    assert captured["endpoint"] == "http://127.0.0.1:4001/v1/semantic-router/decision"


def test_format_result_row_supports_pass_fail_and_na():
    assert format_result_row(
        case_name="match",
        route_id="strong",
        expected_route="strong",
        reason="hard_rule:线上",
    ) == ["PASS", "match", "strong", "strong", "hard_rule:线上"]
    assert format_result_row(
        case_name="mismatch",
        route_id="fast",
        expected_route="strong",
        reason="semantic_similarity",
    )[0] == "FAIL"
    assert format_result_row(
        case_name="no-expected",
        route_id="fast",
        expected_route=None,
        reason="semantic_similarity",
    )[0] == "N/A"


def test_validate_expected_routes_rejects_target_model_name():
    cases = [
        review_decisions.ReviewCase(
            name="bad", payload={"model": DEFAULT_ROUTE_MODEL, "messages": []}, expected_route="pro-router"
        )
    ]
    with pytest.raises(ValueError, match="pro-router"):
        validate_expected_routes(cases, {"fast", "strong"})


def test_run_review_default_table_output_and_success_exit(monkeypatch, tmp_path, capsys):
    path = tmp_path / "cases.yaml"
    path.write_text(
        """
cases:
  - name: expects match
    text: hello
    expected_route: fast
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        review_decisions,
        "call_decision_endpoint",
        lambda endpoint, payload, timeout_s: {
            "route_id": "fast",
            "target_model": "cheap-router",
            "reason": "semantic_similarity",
        },
    )

    exit_code = run_review("http://localhost", path, 1.0)
    output = capsys.readouterr().out
    assert exit_code == 0
    assert "status" in output
    assert "PASS" in output
    assert "Total cases: 1; mismatches: 0; endpoint_errors: 0" in output


def test_run_review_json_output_shape_and_neutral_status(monkeypatch, tmp_path, capsys):
    path = tmp_path / "cases.yaml"
    path.write_text(
        """
cases:
  - name: expected match
    text: hello
    expected_route: fast
  - name: no expectation
    text: hi
""",
        encoding="utf-8",
    )

    responses = iter(
        [
            {
                "route_id": "fast",
                "target_model": "cheap-router",
                "reason": "semantic_similarity",
                "score": 0.88,
            },
            {
                "route_id": "strong",
                "target_model": "pro-router",
                "reason": "semantic_similarity",
                "scores": {"fast": 0.2},
            },
        ]
    )
    monkeypatch.setattr(review_decisions, "call_decision_endpoint", lambda *_args: next(responses))

    exit_code = run_review("http://localhost", path, 1.0, output="json")
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output[0] == {
        "case": "expected match",
        "expected_route": "fast",
        "actual_route": "fast",
        "target_model": "cheap-router",
        "status": "pass",
        "reason": "semantic_similarity",
        "request_payload_model": DEFAULT_ROUTE_MODEL,
        "score": 0.88,
    }
    assert output[1]["case"] == "no expectation"
    assert output[1]["expected_route"] is None
    assert output[1]["status"] is None
    assert output[1]["scores"] == {"fast": 0.2}


def test_run_review_mismatch_expected_route_exits_nonzero(monkeypatch, tmp_path):
    path = tmp_path / "cases.yaml"
    path.write_text(
        """
cases:
  - name: mismatch
    text: hello
    expected_route: fast
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        review_decisions,
        "call_decision_endpoint",
        lambda *_args: {
            "route_id": "strong",
            "target_model": "pro-router",
            "reason": "semantic_similarity",
        },
    )

    assert run_review("http://localhost", path, 1.0, output="json") == 1


def test_run_review_endpoint_exception_table_output_nonzero_and_error_row(monkeypatch, tmp_path, capsys):
    path = tmp_path / "cases.yaml"
    path.write_text(
        """
cases:
  - name: endpoint down
    text: hello
    expected_route: fast
""",
        encoding="utf-8",
    )

    def raise_error(*_args):
        raise RuntimeError("boom")

    monkeypatch.setattr(review_decisions, "call_decision_endpoint", raise_error)

    exit_code = run_review("http://localhost", path, 1.0, output="table")
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "ERROR" in output
    assert "endpoint down" in output
    assert "request failed" in output


def test_run_review_endpoint_exception_json_output_nonzero_and_error_status(monkeypatch, tmp_path, capsys):
    path = tmp_path / "cases.yaml"
    path.write_text(
        """
cases:
  - name: endpoint down
    text: hello
    expected_route: fast
""",
        encoding="utf-8",
    )

    def raise_error(*_args):
        raise RuntimeError("boom with bearer token secret")

    monkeypatch.setattr(review_decisions, "call_decision_endpoint", raise_error)

    exit_code = run_review("http://localhost", path, 1.0, output="json")
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert output[0]["case"] == "endpoint down"
    assert output[0]["status"] == "error"
    assert output[0]["actual_route"] is None
    assert output[0]["error_type"] == "request_error"
    assert "RuntimeError" in output[0]["error_message"]
    assert "bearer" not in output[0]["error_message"].lower()


def test_run_review_includes_successful_cases_before_later_endpoint_error(monkeypatch, tmp_path, capsys):
    path = tmp_path / "cases.yaml"
    path.write_text(
        """
cases:
  - name: first ok
    text: hello
    expected_route: fast
  - name: then fails
    text: hi
    expected_route: strong
""",
        encoding="utf-8",
    )

    def fake_call(*_args):
        if fake_call.calls == 0:
            fake_call.calls += 1
            return {
                "route_id": "fast",
                "target_model": "cheap-router",
                "reason": "semantic_similarity",
            }
        raise RuntimeError("boom")

    fake_call.calls = 0
    monkeypatch.setattr(review_decisions, "call_decision_endpoint", fake_call)

    exit_code = run_review("http://localhost", path, 1.0, output="json")
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert len(output) == 2
    assert output[0]["case"] == "first ok"
    assert output[0]["status"] == "pass"
    assert output[1]["case"] == "then fails"
    assert output[1]["status"] == "error"


def test_run_review_mismatch_and_endpoint_error_both_nonzero(monkeypatch, tmp_path, capsys):
    path = tmp_path / "cases.yaml"
    path.write_text(
        """
cases:
  - name: mismatch
    text: hello
    expected_route: fast
  - name: endpoint error
    text: hi
    expected_route: strong
""",
        encoding="utf-8",
    )

    def fake_call(*_args):
        if fake_call.calls == 0:
            fake_call.calls += 1
            return {
                "route_id": "strong",
                "target_model": "pro-router",
                "reason": "semantic_similarity",
            }
        raise RuntimeError("boom")

    fake_call.calls = 0
    monkeypatch.setattr(review_decisions, "call_decision_endpoint", fake_call)

    exit_code = run_review("http://localhost", path, 1.0, output="json")
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert output[0]["status"] == "fail"
    assert output[1]["status"] == "error"
