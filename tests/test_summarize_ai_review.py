import json
import sys

import pytest

from scripts import summarize_ai_review
from scripts.summarize_ai_review import ReviewResultError, summarize_review_result


def test_summarize_review_result_counts_and_surfaces_human_items():
    result = {
        "schema_version": "intentmux.ai_review_result.v1",
        "items": [
            {
                "request_id": "req-human",
                "agent_decision": "needs_human",
                "confidence": "medium",
                "suggested_expected_route": "deep",
                "summary_zh": "需要确认 hard rule 是否过宽。",
                "evidence": ["reason=hard_rule:token"],
                "human_decision_required": True,
                "redaction_required": False,
            },
            {
                "request_id": "req-misroute",
                "agent_decision": "suspected_misroute",
                "confidence": "high",
                "suggested_expected_route": "lite",
                "summary_zh": "普通解释请求疑似不该升级。",
                "evidence": ["route_id=deep"],
                "human_decision_required": False,
                "redaction_required": True,
            },
        ],
    }

    summary = summarize_review_result(result)

    assert summary["summary"]["decision_counts"] == {
        "needs_human": 1,
        "suspected_misroute": 1,
    }
    assert summary["human_audit_items"][0]["request_id"] == "req-human"
    assert summary["suspected_regression_cases"][0]["request_id"] == "req-misroute"


def test_summarize_review_result_rejects_unknown_decision():
    with pytest.raises(ReviewResultError, match="agent_decision"):
        summarize_review_result(
            {
                "schema_version": "intentmux.ai_review_result.v1",
                "items": [
                    {
                        "request_id": "req-1",
                        "agent_decision": "invented",
                        "confidence": "high",
                        "suggested_expected_route": "unknown",
                        "summary_zh": "bad",
                        "evidence": [],
                        "human_decision_required": False,
                        "redaction_required": False,
                    }
                ],
            }
        )


def test_summarize_review_result_rejects_raw_prompt_keys():
    with pytest.raises(ReviewResultError, match="raw prompt"):
        summarize_review_result(
            {
                "schema_version": "intentmux.ai_review_result.v1",
                "items": [
                    {
                        "request_id": "req-1",
                        "agent_decision": "watch_only",
                        "confidence": "low",
                        "suggested_expected_route": "unknown",
                        "summary_zh": "bad",
                        "evidence": [],
                        "latest_user_text": "should not be here",
                        "human_decision_required": False,
                        "redaction_required": False,
                    }
                ],
            }
        )


def test_summarize_ai_review_cli_writes_json_and_markdown(tmp_path, monkeypatch):
    input_path = tmp_path / "ai-result.json"
    json_output = tmp_path / "summary.json"
    md_output = tmp_path / "summary.md"
    input_path.write_text(
        json.dumps(
            {
                "schema_version": "intentmux.ai_review_result.v1",
                "items": [
                    {
                        "request_id": "req-1",
                        "agent_decision": "watch_only",
                        "confidence": "low",
                        "suggested_expected_route": "unknown",
                        "summary_zh": "继续观察。",
                        "evidence": ["reason=low_confidence"],
                        "human_decision_required": False,
                        "redaction_required": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "summarize_ai_review.py",
            "--input",
            str(input_path),
            "--json-output",
            str(json_output),
            "--markdown-output",
            str(md_output),
        ],
    )

    summarize_ai_review.main()

    assert json.loads(json_output.read_text(encoding="utf-8"))["schema_version"] == "intentmux.ai_review_summary.v1"
    assert "AI Review Summary" in md_output.read_text(encoding="utf-8")
