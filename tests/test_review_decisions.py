from __future__ import annotations

import json

from scripts.review_decisions import DEFAULT_ROUTE_MODEL, format_result_row, load_cases


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
