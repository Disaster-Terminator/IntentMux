from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.route_threshold_sweep_report import (
    build_threshold_sweep_report,
    build_threshold_sweep_from_source,
    case_ids,
    sweep_eval_payload,
)


def eval_payload(threshold: float, cases: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema": "intentmux-route-eval-v1",
        "baseline": f"threshold-{threshold:.2f}",
        "threshold": threshold,
        "margin": 0.04,
        "cases": cases,
    }


def test_case_ids_prefers_explicit_ids_and_falls_back_to_hash():
    payload = eval_payload(
        0.4,
        [
            {"id": "explicit", "text_sha256": "ignored"},
            {"text_sha256": "abc123"},
        ],
    )

    assert case_ids(payload) == ["explicit", "sha256:abc123"]


def test_threshold_sweep_report_compares_candidates_with_same_case_set():
    cases = [
        {"id": "lite1", "expect": "lite", "actual_route": "lite", "passed": True},
        {"id": "deep1", "expect": "deep", "actual_route": "lite", "passed": False},
    ]
    report = build_threshold_sweep_report(
        [
            ("threshold-0.35", eval_payload(0.35, cases)),
            (
                "threshold-0.45",
                eval_payload(
                    0.45,
                    [
                        {
                            "id": "lite1",
                            "expect": "lite",
                            "actual_route": "lite",
                            "passed": True,
                        },
                        {
                            "id": "deep1",
                            "expect": "deep",
                            "actual_route": "deep",
                            "passed": True,
                        },
                    ],
                ),
            ),
        ],
        false_lite_weight=10.0,
        false_deep_weight=1.0,
    )

    assert report["schema"] == "intentmux-threshold-sweep-v1"
    assert report["case_count"] == 2
    assert report["recommended_candidate"] == "threshold-0.45"
    assert [
        (candidate["label"], candidate["threshold"], candidate["weighted_route_cost"])
        for candidate in report["candidates"]
    ] == [
        ("threshold-0.45", 0.45, 0.0),
        ("threshold-0.35", 0.35, 5.0),
    ]


def test_threshold_sweep_report_rejects_mismatched_case_sets():
    with pytest.raises(ValueError, match="same eval case set"):
        build_threshold_sweep_report(
            [
                ("a", eval_payload(0.35, [{"id": "one"}])),
                ("b", eval_payload(0.45, [{"id": "two"}])),
            ]
        )


def test_sweep_eval_payload_reclassifies_embedding_scores_without_text():
    source = eval_payload(
        0.4,
        [
            {
                "id": "near-deep",
                "text": "private prompt must not copy",
                "expect": "deep",
                "actual_route": "lite",
                "passed": False,
                "reason": "low_confidence",
                "score": 0.43,
                "second_score": 0.35,
                "score_margin": 0.08,
                "top_route_id": "deep",
            },
            {
                "id": "hard-rule",
                "expect": "deep",
                "actual_route": "deep",
                "passed": True,
                "reason": "hard_rule:生产事故",
            },
        ],
    )

    swept = sweep_eval_payload(
        source,
        threshold=0.42,
        margin=0.04,
        fallback_route_id="lite",
    )

    assert swept["baseline"] == "threshold-0.42"
    assert swept["threshold"] == 0.42
    assert swept["cases"][0]["actual_route"] == "deep"
    assert swept["cases"][0]["passed"] is True
    assert swept["cases"][0]["reason"] == "sweep:embedding"
    assert "text" not in swept["cases"][0]
    assert swept["cases"][1]["actual_route"] == "deep"
    assert swept["cases"][1]["reason"] == "hard_rule:生产事故"


def test_build_threshold_sweep_from_source_ranks_offline_thresholds():
    source = eval_payload(
        0.4,
        [
            {
                "id": "lite1",
                "expect": "lite",
                "actual_route": "lite",
                "passed": True,
                "reason": "embedding",
                "score": 0.6,
                "second_score": 0.5,
                "score_margin": 0.1,
                "top_route_id": "deep",
            },
            {
                "id": "deep1",
                "expect": "deep",
                "actual_route": "lite",
                "passed": False,
                "reason": "low_confidence",
                "score": 0.43,
                "second_score": 0.35,
                "score_margin": 0.08,
                "top_route_id": "deep",
            },
        ],
    )

    report = build_threshold_sweep_from_source(
        source,
        thresholds=[0.42, 0.7],
        margin=0.04,
        fallback_route_id="lite",
    )

    assert [candidate["label"] for candidate in report["candidates"]] == [
        "threshold-0.42",
        "threshold-0.70",
    ]
    assert report["candidates"][0]["false_deep_count"] == 1
    assert report["candidates"][1]["false_lite_count"] == 1


def test_threshold_sweep_cli_writes_json_and_markdown(tmp_path: Path):
    low_path = tmp_path / "threshold-0.35.json"
    high_path = tmp_path / "threshold-0.45.json"
    out_json = tmp_path / "sweep.json"
    out_md = tmp_path / "sweep.md"
    low_path.write_text(
        json.dumps(
            eval_payload(
                0.35,
                [
                    {"id": "lite1", "expect": "lite", "actual_route": "lite", "passed": True},
                    {"id": "deep1", "expect": "deep", "actual_route": "lite", "passed": False},
                ],
            )
        ),
        encoding="utf-8",
    )
    high_path.write_text(
        json.dumps(
            eval_payload(
                0.45,
                [
                    {"id": "lite1", "expect": "lite", "actual_route": "lite", "passed": True},
                    {"id": "deep1", "expect": "deep", "actual_route": "deep", "passed": True},
                ],
            )
        ),
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            "scripts/route_threshold_sweep_report.py",
            "--eval-json",
            f"threshold-0.35={low_path}",
            "--eval-json",
            f"threshold-0.45={high_path}",
            "--json-output",
            str(out_json),
            "--markdown-output",
            str(out_md),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["recommended_candidate"] == "threshold-0.45"
    markdown = out_md.read_text(encoding="utf-8")
    assert "# IntentMux Threshold Sweep Report" in markdown
    assert "threshold-0.45" in markdown


def test_threshold_sweep_cli_can_build_from_single_source_eval(tmp_path: Path):
    source_path = tmp_path / "source.json"
    out_json = tmp_path / "sweep.json"
    out_md = tmp_path / "sweep.md"
    source_path.write_text(
        json.dumps(
            eval_payload(
                0.4,
                [
                    {
                        "id": "deep1",
                        "expect": "deep",
                        "actual_route": "lite",
                        "passed": False,
                        "reason": "low_confidence",
                        "score": 0.43,
                        "second_score": 0.35,
                        "score_margin": 0.08,
                        "top_route_id": "deep",
                    }
                ],
            )
        ),
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            "scripts/route_threshold_sweep_report.py",
            "--source-eval-json",
            str(source_path),
            "--threshold",
            "0.42",
            "--threshold",
            "0.7",
            "--json-output",
            str(out_json),
            "--markdown-output",
            str(out_md),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["case_count"] == 1
    assert {candidate["threshold"] for candidate in payload["candidates"]} == {0.42, 0.7}
