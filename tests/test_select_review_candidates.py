from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.select_review_candidates import (
    build_review_candidate_report,
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
            "target_model": "cheap-router",
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
            "target_model": "cheap-router",
            "reason": "embedding_error",
            "duration_ms": 900,
            "body": {"messages": ["must not leak"]},
        },
        {
            "event": "route_complete",
            "timestamp": "2026-05-13T00:00:02Z",
            "request_id": "req-400",
            "route_id": "strong",
            "target_model": "pro-router",
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
            "target_model": "pro-router",
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
            "target_model": "pro-router",
            "reason": "embedding",
            "score": 0.8,
            "second_score": 0.77,
            "duration_ms": 600,
        },
        {
            "event": "route_complete",
            "timestamp": "2026-05-13T00:00:05Z",
            "request_id": "req-slow",
            "route_id": "fast",
            "target_model": "cheap-router",
            "reason": "embedding",
            "score": 0.9,
            "second_score": 0.1,
            "duration_ms": 100_000,
        },
        {
            "event": "route_complete",
            "timestamp": "2026-05-13T00:00:06Z",
            "request_id": "req-normal",
            "route_id": "fast",
            "target_model": "cheap-router",
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
        "req-low",
        "req-err",
        "req-400",
        "req-slow",
        "req-near-threshold",
        "req-near-margin",
    ]
    assert candidates[0]["review_reasons"] == ["low_confidence", "near_margin"]
    assert candidates[1]["review_reasons"] == ["embedding_error"]
    assert candidates[2]["review_reasons"] == ["upstream_non_2xx"]
    assert candidates[3]["review_reasons"] == ["slow_request"]
    assert candidates[4]["review_reasons"] == ["near_threshold"]
    assert candidates[5]["review_reasons"] == ["near_margin"]

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
                "target_model": "cheap-router",
                "reason": "low_confidence",
                "duration_ms": 100,
            },
            {
                "event": "route_complete",
                "request_id": "req-normal",
                "route_id": "fast",
                "target_model": "cheap-router",
                "reason": "embedding",
                "duration_ms": 100,
            },
        ],
        log_paths=["routes.jsonl"],
    )

    assert report["summary"] == {
        "input_records": 2,
        "candidate_count": 1,
        "review_reasons": {"low_confidence": 1},
        "routes": {"fast": 1},
        "targets": {"cheap-router": 1},
        "log_paths": ["routes.jsonl"],
    }
    assert report["candidates"][0]["request_id"] == "req-low"


def test_render_markdown_is_audit_friendly():
    markdown = render_markdown(
        {
            "summary": {
                "input_records": 2,
                "candidate_count": 1,
                "review_reasons": {"low_confidence": 1},
                "routes": {"fast": 1},
                "targets": {"cheap-router": 1},
                "log_paths": ["routes.jsonl"],
            },
            "candidates": [
                {
                    "timestamp": "2026-05-13T00:00:00Z",
                    "request_id": "req-low",
                    "route_id": "fast",
                    "target_model": "cheap-router",
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
    assert "| req-low | fast | cheap-router | low_confidence |" in markdown


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
                "target_model": "cheap-router",
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
