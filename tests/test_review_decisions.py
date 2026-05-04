from __future__ import annotations

import json

import pytest

from scripts.review_decisions import ReviewResult, format_result_line, load_cases


def test_load_cases_from_yaml_sample():
    cases = load_cases(__import__("pathlib").Path("tests/samples/review_decisions.yaml"))
    assert len(cases) == 2
    assert cases[0].name == "hard-rule-online"
    assert cases[0].expected_target == "pro-router"
    assert cases[1].messages == [{"role": "user", "content": "给我一个轻量总结"}]


def test_load_cases_from_jsonl(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"name": "a", "text": "hello", "expected_target": "cheap-router"}),
                json.dumps({"name": "b", "messages": [{"role": "user", "content": "world"}]}),
            ]
        ),
        encoding="utf-8",
    )
    cases = load_cases(path)
    assert [c.name for c in cases] == ["a", "b"]
    assert cases[0].text == "hello"
    assert cases[1].messages is not None


def test_format_result_line_pass_and_na():
    passed = format_result_line(
        ReviewResult(
            case_name="online",
            selected_target="pro-router",
            expected_target="pro-router",
            reason="hard_rule:线上",
        )
    )
    not_scored = format_result_line(
        ReviewResult(
            case_name="summary",
            selected_target="cheap-router",
            expected_target=None,
            reason="embedding",
        )
    )
    assert passed.startswith("PASS\tonline\tpro-router\tpro-router\thard_rule:线上")
    assert not_scored.startswith("N/A\tsummary\tcheap-router\t-\tembedding")


def test_load_cases_rejects_missing_content(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("- name: broken\n", encoding="utf-8")
    with pytest.raises(ValueError, match="either text or messages"):
        load_cases(path)
