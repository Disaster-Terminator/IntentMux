from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.select_review_candidates import (
    build_review_candidate_report,
    load_route_thresholds,
    render_markdown,
    select_review_candidates,
)


def test_select_review_candidates_prioritizes_reviewable_metadata_only():
    records = [
        {
            "event": "route_complete",
            "timestamp": "2026-05-13T00:00:00Z",
            "request_id": "req-low",
            "route_id": "fast",
            "target_model": "lite-upstream",
            "reason": "low_confidence",
            "score": 0.51,
            "second_score": 0.49,
            "duration_ms": 1000,
            "prompt": "must not leak",
            "authorization": "Bearer secret",
        },
        {
            "event": "route_complete",
            "timestamp": "2026-05-13T00:00:01Z",
            "request_id": "req-err",
            "route_id": "fast",
            "target_model": "lite-upstream",
            "reason": "embedding_error",
            "duration_ms": 900,
            "body": {"messages": ["must not leak"]},
        },
        {
            "event": "route_complete",
            "timestamp": "2026-05-13T00:00:02Z",
            "request_id": "req-400",
            "route_id": "strong",
            "target_model": "deep-upstream",
            "reason": "embedding",
            "score": 0.7,
            "second_score": 0.3,
            "upstream_status": 400,
            "duration_ms": 800,
        },
        {
            "event": "route_complete",
            "timestamp": "2026-05-13T00:00:03Z",
            "request_id": "req-near-threshold",
            "route_id": "strong",
            "target_model": "deep-upstream",
            "reason": "embedding",
            "score": 0.57,
            "second_score": 0.2,
            "duration_ms": 700,
        },
        {
            "event": "route_complete",
            "timestamp": "2026-05-13T00:00:04Z",
            "request_id": "req-near-margin",
            "route_id": "strong",
            "target_model": "deep-upstream",
            "reason": "embedding",
            "score": 0.8,
            "second_score": 0.77,
            "duration_ms": 600,
        },
        {
            "event": "route_complete",
            "timestamp": "2026-05-13T00:00:05Z",
            "request_id": "req-hard-rule",
            "route_id": "strong",
            "target_model": "deep-upstream",
            "reason": "hard_rule:token",
            "duration_ms": 500,
        },
        {
            "event": "route_complete",
            "timestamp": "2026-05-13T00:00:06Z",
            "request_id": "req-slow",
            "route_id": "fast",
            "target_model": "lite-upstream",
            "reason": "embedding",
            "score": 0.9,
            "second_score": 0.1,
            "duration_ms": 100_000,
        },
        {
            "event": "route_complete",
            "timestamp": "2026-05-13T00:00:07Z",
            "request_id": "req-normal",
            "route_id": "fast",
            "target_model": "lite-upstream",
            "reason": "embedding",
            "score": 0.9,
            "second_score": 0.1,
            "duration_ms": 100,
        },
    ]

    candidates = select_review_candidates(
        records,
        threshold=0.58,
        threshold_window=0.02,
        margin=0.04,
        margin_window=0.02,
        slow_duration_ms=60_000,
        limit=20,
    )

    request_ids = [candidate["request_id"] for candidate in candidates]
    assert request_ids == [
        "req-hard-rule",
        "req-low",
        "req-err",
        "req-400",
        "req-slow",
        "req-near-threshold",
        "req-near-margin",
    ]
    assert candidates[0]["review_reasons"] == ["hard_rule"]
    assert candidates[1]["review_reasons"] == ["low_confidence", "near_margin"]
    assert candidates[2]["review_reasons"] == ["embedding_error"]
    assert candidates[3]["review_reasons"] == ["upstream_non_2xx"]
    assert candidates[4]["review_reasons"] == ["slow_request"]
    assert candidates[5]["review_reasons"] == ["near_threshold"]
    assert candidates[6]["review_reasons"] == ["near_margin"]

    encoded = json.dumps(candidates, ensure_ascii=False)
    assert "must not leak" not in encoded
    assert "Bearer secret" not in encoded
    assert "prompt" not in encoded
    assert "body" not in encoded
    assert "authorization" not in encoded


def test_build_review_candidate_report_counts_reasons_and_inputs():
    report = build_review_candidate_report(
        [
            {
                "event": "route_complete",
                "request_id": "req-low",
                "route_id": "fast",
                "target_model": "lite-upstream",
                "reason": "low_confidence",
                "duration_ms": 100,
                "format_signals": {
                    "tools_present": True,
                    "tool_history": True,
                    "response_format_present": False,
                    "message_count": 4,
                },
            },
            {
                "event": "route_complete",
                "request_id": "req-normal",
                "route_id": "fast",
                "target_model": "lite-upstream",
                "reason": "embedding",
                "duration_ms": 100,
            },
        ],
        log_paths=["routes.jsonl"],
    )

    assert report["summary"] == {
        "input_records": 2,
        "candidate_count": 1,
        "candidate_prompt_matches": 0,
        "format_signal_counts": {"tool_history": 1, "tools_present": 1},
        "review_reasons": {"low_confidence": 1},
        "routes": {"fast": 1},
        "targets": {"lite-upstream": 1},
        "hard_rules": {},
        "log_paths": ["routes.jsonl"],
        "prompt_log_paths": [],
    }
    assert report["candidates"][0]["request_id"] == "req-low"
    assert report["candidates"][0]["format_signals"] == {
        "tools_present": True,
        "tool_history": True,
        "response_format_present": False,
        "message_count": 4,
    }


def test_build_review_candidate_report_joins_prompt_reviews_without_inferring_source_or_leaking_text():
    report = build_review_candidate_report(
        [
            {
                "event": "route_complete",
                "timestamp": "2026-05-13T00:00:00Z",
                "request_id": "req-agent",
                "route_id": "fast",
                "target_model": "lite-upstream",
                "reason": "low_confidence",
                "duration_ms": 100,
            },
            {
                "event": "route_complete",
                "timestamp": "2026-05-13T00:00:01Z",
                "request_id": "req-normal",
                "route_id": "fast",
                "target_model": "lite-upstream",
                "reason": "low_confidence",
                "duration_ms": 100,
            },
        ],
        prompt_records=[
            {
                "event": "prompt_review",
                "request_id": "req-agent",
                "latest_user_text": "Agent framework wrapper. User task: Review this patch and report.",
                "truncated": True,
            },
            {
                "event": "prompt_review",
                "request_id": "req-normal",
                "latest_user_text": "Summarize this paragraph.",
                "truncated": False,
            },
        ],
        prompt_log_paths=["prompts.jsonl"],
    )

    assert report["summary"]["candidate_prompt_matches"] == 2
    agent_candidate = report["candidates"][0]
    assert agent_candidate["request_id"] == "req-agent"
    assert agent_candidate["prompt_review"] == {
        "matched": True,
        "truncated": True,
        "text_chars": 65,
    }
    encoded = json.dumps(report, ensure_ascii=False)
    assert "Review this patch" not in encoded
    assert "Summarize this paragraph" not in encoded


def test_build_review_candidate_report_counts_hard_rule_keywords():
    report = build_review_candidate_report(
        [
            {
                "event": "route_complete",
                "request_id": "req-token",
                "route_id": "strong",
                "target_model": "deep-upstream",
                "reason": "hard_rule:token",
                "duration_ms": 100,
            },
            {
                "event": "route_complete",
                "request_id": "req-security",
                "route_id": "strong",
                "target_model": "deep-upstream",
                "reason": "hard_rule:安全",
                "duration_ms": 100,
            },
        ],
    )

    assert report["summary"]["review_reasons"] == {"hard_rule": 2}
    assert report["summary"]["hard_rules"] == {"安全": 1, "token": 1}


def test_load_route_thresholds_reads_routes_config(tmp_path: Path):
    routes_path = tmp_path / "routes.yaml"
    routes_path.write_text(
        """
threshold: 0.55
margin: 0.07
routes:
  fast:
    utterances:
      - hi
""",
        encoding="utf-8",
    )

    assert load_route_thresholds(routes_path) == (0.55, 0.07)


def test_render_markdown_is_audit_friendly():
    markdown = render_markdown(
        {
            "summary": {
                "input_records": 2,
                "candidate_count": 1,
                "review_reasons": {"low_confidence": 1},
                "routes": {"fast": 1},
                "targets": {"lite-upstream": 1},
                "hard_rules": {},
                "log_paths": ["routes.jsonl"],
            },
            "candidates": [
                {
                    "timestamp": "2026-05-13T00:00:00Z",
                    "request_id": "req-low",
                    "route_id": "fast",
                    "target_model": "lite-upstream",
                    "reason": "low_confidence",
                    "score": None,
                    "second_score": None,
                    "duration_ms": 100.0,
                    "upstream_status": None,
                    "review_reasons": ["low_confidence"],
                }
            ],
        }
    )

    assert "# IntentMux Review Candidates" in markdown
    assert "- candidate_count: 1" in markdown
    assert "| req-low | fast | lite-upstream | low_confidence |" in markdown


def test_main_writes_json_and_markdown(tmp_path: Path):
    log_path = tmp_path / "routes.jsonl"
    json_path = tmp_path / "candidates.json"
    md_path = tmp_path / "candidates.md"
    log_path.write_text(
        json.dumps(
            {
                "event": "route_complete",
                "timestamp": "2026-05-13T00:00:00Z",
                "request_id": "req-low",
                "route_id": "fast",
                "target_model": "lite-upstream",
                "reason": "low_confidence",
                "duration_ms": 100,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            "scripts/select_review_candidates.py",
            str(log_path),
            "--json-output",
            str(json_path),
            "--markdown-output",
            str(md_path),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["summary"]["candidate_count"] == 1
    assert md_path.read_text(encoding="utf-8").startswith("# IntentMux Review Candidates")


def test_main_uses_default_routes_threshold(tmp_path: Path):
    log_path = tmp_path / "routes.jsonl"
    json_path = tmp_path / "candidates.json"
    log_path.write_text(
        json.dumps(
            {
                "event": "route_complete",
                "timestamp": "2026-05-13T00:00:00Z",
                "request_id": "req-near-config-threshold",
                "route_id": "fast",
                "target_model": "lite-upstream",
                "reason": "embedding",
                "score": 0.535,
                "duration_ms": 100,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            "scripts/select_review_candidates.py",
            str(log_path),
            "--json-output",
            str(json_path),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["summary"]["candidate_count"] == 1
    assert payload["candidates"][0]["review_reasons"] == ["near_threshold"]
