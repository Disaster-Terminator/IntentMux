from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.route_calibration_report import (
    build_report,
    coverage,
    infer_language,
    parse_thresholds,
    render_markdown,
    summarize_eval,
)


def test_parse_thresholds_sorts_and_deduplicates_values():
    assert parse_thresholds("0.65, 0.35,0.65") == [0.35, 0.65]


def test_parse_thresholds_rejects_empty_value():
    with pytest.raises(ValueError, match="at least one"):
        parse_thresholds(" , ")


def test_summarize_eval_reports_deep_call_rate_and_slices():
    payload = {
        "cases": [
            {
                "id": "lite1",
                "slice": "lite_general_zh",
                "expect": "lite",
                "actual_route": "lite",
                "reason": "embedding",
                "passed": True,
            },
            {
                "id": "deep1",
                "slice": "deep_code_zh",
                "expect": "deep",
                "actual_route": "deep",
                "reason": "embedding",
                "passed": True,
            },
        ]
    }

    summary = summarize_eval("current-router", payload, exit_code=0)

    assert summary["total"] == 2
    assert summary["pass_rate"] == 1.0
    assert summary["deep_call_rate"] == 0.5
    assert summary["slice_metrics"]["lite_general_zh"]["deep_call_rate"] == 0.0
    assert summary["slice_metrics"]["deep_code_zh"]["deep_call_rate"] == 1.0


def test_build_report_selects_best_threshold_by_quality_then_cost():
    eval_payloads = {
        "current-router": {
            "cases": [
                {"expect": "lite", "actual_route": "lite", "passed": True},
                {"expect": "deep", "actual_route": "deep", "passed": True},
            ]
        },
        "threshold:0.35": {
            "cases": [
                {"expect": "lite", "actual_route": "deep", "passed": False},
                {"expect": "deep", "actual_route": "deep", "passed": True},
            ]
        },
        "threshold:0.55": {
            "cases": [
                {"expect": "lite", "actual_route": "lite", "passed": True},
                {"expect": "deep", "actual_route": "deep", "passed": True},
            ]
        },
    }
    run_results = {
        "current-router": {"exit_code": 0},
        "threshold:0.35": {"exit_code": 1},
        "threshold:0.55": {"exit_code": 0},
    }

    report = build_report(
        eval_payloads=eval_payloads,
        run_results=run_results,
        threshold_labels=["threshold:0.35", "threshold:0.55"],
        cases_path=Path("cases.yaml"),
        routes_path=Path("routes.yaml"),
    )

    assert report["schema"] == "intentmux-route-calibration-v1"
    assert report["recommendation"]["status"] == "evidence_ready"
    assert report["recommendation"]["best_threshold_label"] == "threshold:0.55"
    assert len(report["threshold_curve"]) == 2


def test_coverage_counts_languages_and_slices():
    payload = {
        "cases": [
            {"text": "帮我总结", "slice": "lite_general_zh"},
            {"text": "Fix this bug", "slice": "deep_debug_en"},
            {"text": "123", "slice": ""},
        ]
    }

    assert infer_language("帮我总结") == "zh"
    assert infer_language("Fix this bug") == "en"
    assert infer_language("123") == "unknown"
    assert coverage(payload) == {
        "total": 3,
        "languages": {"zh": 1, "en": 1, "unknown": 1},
        "slices": {"lite_general_zh": 1, "deep_debug_en": 1, "unknown": 1},
        "bilingual_sample_count": 2,
    }


def test_render_markdown_includes_baselines_threshold_curve_and_slices():
    report = {
        "cases_path": "cases.yaml",
        "routes_path": "routes.yaml",
        "coverage": {
            "total": 1,
            "languages": {"zh": 1},
            "slices": {"lite_general_zh": 1},
            "bilingual_sample_count": 1,
        },
        "recommendation": {"status": "evidence_ready"},
        "baselines": {
            "current-router": {
                "pass_rate": 1.0,
                "deep_call_rate": 0.5,
                "exit_code": 0,
                "slice_metrics": {
                    "lite_general_zh": {
                        "total": 1,
                        "pass_rate": 1.0,
                        "deep_call_rate": 0.0,
                    }
                },
            }
        },
        "threshold_curve": [
            {
                "label": "threshold:0.55",
                "pass_rate": 1.0,
                "deep_call_rate": 0.5,
                "exit_code": 0,
            }
        ],
    }

    markdown = render_markdown(report)

    assert "# IntentMux Route Calibration Report" in markdown
    assert "## Baseline Comparison" in markdown
    assert "current-router: pass_rate=100.00% deep_call_rate=50.00%" in markdown
    assert "threshold:0.55: pass_rate=100.00% deep_call_rate=50.00%" in markdown
    assert "lite_general_zh: total=1 pass_rate=100.00%" in markdown
    assert "## Coverage" in markdown


def test_route_calibration_report_cli_writes_bounded_artifacts(tmp_path: Path):
    cases = tmp_path / "cases.yaml"
    work_dir = tmp_path / "work"
    json_output = tmp_path / "report.json"
    markdown_output = tmp_path / "report.md"
    cases.write_text(
        """
cases:
  - id: lite_001
    slice: lite_general_zh
    text: 帮我总结这段话
    expect: lite
  - id: deep_001
    slice: deep_code_zh
    text: 这个 PR 会不会引入回归
    expect: deep
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/route_calibration_report.py",
            "--cases",
            str(cases),
            "--work-dir",
            str(work_dir),
            "--json-output",
            str(json_output),
            "--markdown-output",
            str(markdown_output),
            "--mock-embeddings",
            "--thresholds",
            "0.35,0.55",
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    paths = json.loads(result.stdout)
    report = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
    markdown = Path(paths["markdown"]).read_text(encoding="utf-8")
    assert paths == {"json": str(json_output), "markdown": str(markdown_output)}
    assert report["schema"] == "intentmux-route-calibration-v1"
    assert "always-lite" in report["baselines"]
    assert report["coverage"]["languages"] == {"zh": 2}
    assert report["coverage"]["slices"] == {"lite_general_zh": 1, "deep_code_zh": 1}
    assert [point["label"] for point in report["threshold_curve"]] == [
        "threshold:0.35",
        "threshold:0.55",
    ]
    assert "## Threshold Curve" in markdown
    assert "## Coverage" in markdown
