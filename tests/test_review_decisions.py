from __future__ import annotations

from pathlib import Path

from scripts.review_decisions import ReviewCase, format_result_row, load_cases


def test_load_cases_from_yaml_sample():
    cases = load_cases(Path("tests/samples/review_decisions_cases.yaml"))
    assert len(cases) == 2
    assert cases[0] == ReviewCase(
        name="online-bug",
        text="这个线上 bug 为什么偶发",
        expected_target="pro-router",
    )
    assert cases[1].messages == [{"role": "user", "content": "请帮我润色这段说明"}]


def test_format_result_row_with_expected():
    row = format_result_row("online-bug", "pro-router", "pro-router", "hard_rule:线上")
    assert row == "PASS\tonline-bug\tpro-router\tpro-router\thard_rule:线上"


def test_format_result_row_without_expected():
    row = format_result_row("low-risk", "cheap-router", None, "embedding")
    assert row == "-\tlow-risk\tcheap-router\t\tembedding"
