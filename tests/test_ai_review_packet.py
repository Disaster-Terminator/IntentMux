import json
import sys

from scripts import prepare_ai_review_packet
from scripts.prepare_ai_review_packet import build_ai_review_packet


def test_build_ai_review_packet_groups_candidates_without_prompt_text():
    candidate_report = {
        "summary": {"candidate_count": 4},
        "candidates": [
            {
                "request_id": "hard",
                "route_id": "deep",
                "target_model": "pro",
                "reason": "hard_rule:token",
                "review_reasons": ["hard_rule"],
                "prompt_review": {"matched": True, "truncated": False, "text_chars": 20},
            },
            {
                "request_id": "low",
                "route_id": "lite",
                "target_model": "cheap",
                "reason": "low_confidence",
                "review_reasons": ["low_confidence", "near_margin"],
                "score": 0.51,
                "second_score": 0.49,
                "score_margin": 0.02,
                "threshold": 0.4,
                "margin": 0.04,
                "top_route_id": "deep",
                "second_route_id": "lite",
                "match_source": "swebench_dev_eval",
                "match_index": 12,
                "match_text_sha256": "abc123",
                "match_score": 0.51,
                "match_provenance": "aurelio_hybrid_exact",
                "prompt_review": {"matched": True, "truncated": False, "text_chars": 30},
            },
            {
                "request_id": "watch",
                "route_id": "lite",
                "target_model": "cheap",
                "reason": "low_confidence",
                "review_reasons": ["low_confidence"],
            },
            {
                "request_id": "truncated",
                "route_id": "lite",
                "target_model": "cheap",
                "reason": "low_confidence",
                "review_reasons": ["low_confidence"],
                "prompt_review": {"matched": True, "truncated": True, "text_chars": 20000},
            },
        ],
    }

    packet = build_ai_review_packet(candidate_report)

    assert packet["schema_version"] == "intentmux.ai_review_packet.v1"
    assert packet["privacy_mode"] == "metadata_only"
    assert packet["summary"]["groups"] == {
        "needs_human_decision": 1,
        "likely_regression_case": 1,
        "privacy_blocked": 1,
        "watch_only": 1,
    }
    assert [item["group"] for item in packet["candidates"]] == [
        "needs_human_decision",
        "likely_regression_case",
        "watch_only",
        "privacy_blocked",
    ]
    low_candidate = packet["candidates"][1]
    assert low_candidate["score_margin"] == 0.02
    assert low_candidate["threshold"] == 0.4
    assert low_candidate["margin"] == 0.04
    assert low_candidate["top_route_id"] == "deep"
    assert low_candidate["second_route_id"] == "lite"
    assert low_candidate["match_source"] == "swebench_dev_eval"
    assert low_candidate["match_index"] == 12
    assert low_candidate["match_text_sha256"] == "abc123"
    assert low_candidate["match_score"] == 0.51
    assert low_candidate["match_provenance"] == "aurelio_hybrid_exact"
    assert "latest_user_text" not in str(packet)
    assert all(item["prompt_excerpt"] is None for item in packet["candidates"])


def test_build_ai_review_packet_includes_excerpt_only_when_raw_local_enabled():
    candidate_report = {
        "summary": {"candidate_count": 1},
        "candidates": [
            {
                "request_id": "req-1",
                "route_id": "lite",
                "target_model": "cheap",
                "reason": "low_confidence",
                "review_reasons": ["low_confidence"],
                "prompt_review": {"matched": True, "truncated": False, "text_chars": 12},
            }
        ],
    }
    prompt_records = [
        {
            "event": "prompt_review",
            "request_id": "req-1",
            "latest_user_text": "请分析这个问题",
        }
    ]

    metadata_only = build_ai_review_packet(candidate_report, prompt_records=prompt_records)
    raw_local = build_ai_review_packet(
        candidate_report,
        prompt_records=prompt_records,
        include_prompt_text="raw_local",
        max_prompt_chars=5,
    )

    assert metadata_only["candidates"][0]["prompt_excerpt"] is None
    assert raw_local["privacy_mode"] == "raw_local"
    assert raw_local["candidates"][0]["prompt_excerpt"] == "请分析这个"


def test_prepare_ai_review_packet_cli_writes_json_and_markdown(tmp_path, monkeypatch):
    input_path = tmp_path / "candidates.json"
    json_output = tmp_path / "packet.json"
    md_output = tmp_path / "packet.md"
    input_path.write_text(
        json.dumps(
            {
                "summary": {"candidate_count": 1},
                "candidates": [
                    {
                        "request_id": "req-1",
                        "route_id": "lite",
                        "target_model": "cheap",
                        "reason": "low_confidence",
                        "review_reasons": ["low_confidence"],
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
            "prepare_ai_review_packet.py",
            "--input",
            str(input_path),
            "--json-output",
            str(json_output),
            "--markdown-output",
            str(md_output),
        ],
    )

    prepare_ai_review_packet.main()

    assert json.loads(json_output.read_text(encoding="utf-8"))["schema_version"] == "intentmux.ai_review_packet.v1"
    assert "AI Review Packet" in md_output.read_text(encoding="utf-8")
