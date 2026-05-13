from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.route_quality_report import (
    build_quality_report,
    parse_eval_output,
    render_markdown,
)


def test_parse_eval_output_counts_routes_and_reasons():
    output = "\n".join(
        [
            "PASS\tfast\tfast\tcheap-router\tlow_confidence\t翻译成中文",
            "PASS\tstrong\tstrong\tpro-router\tembedding\t这个 bug 为什么偶发",
            "FAIL\tstrong\tfast\tcheap-router\tlow_confidence\t分析这个 PR",
            "",
            "1 eval case(s) failed.",
        ]
    )

    result = parse_eval_output(output)

    assert result.total == 3
    assert result.passed == 2
    assert result.failed == 1
    assert result.expected_routes == {"fast": 1, "strong": 2}
    assert result.actual_routes == {"fast": 2, "strong": 1}
    assert result.reasons == {"embedding": 1, "low_confidence": 2}
    assert result.failures == [
        {
            "expect": "strong",
            "actual": "fast",
            "target_model": "cheap-router",
            "reason": "low_confidence",
            "text": "分析这个 PR",
        }
    ]


def test_build_quality_report_combines_eval_and_route_summary():
    eval_output = "\n".join(
        [
            "PASS\tfast\tfast\tcheap-router\tlow_confidence\t翻译成中文",
            "PASS\tstrong\tstrong\tpro-router\tembedding\t分析这个 PR",
        ]
    )
    route_summary = {
        "total": 10,
        "routes": {"fast": 8, "strong": 2},
        "reasons": {"low_confidence": 7, "embedding": 3},
        "not_ok": 1,
        "upstream_statuses": {"200": 9, "400": 1},
        "duration_percentiles_ms": {"p95": 1200.0},
    }

    report = build_quality_report(
        eval_output=eval_output,
        route_summary=route_summary,
        route_bank_path="examples/route_bank.sample.yaml",
    )

    assert report["eval"]["pass_rate"] == 1.0
    assert report["traffic"]["low_confidence_rate"] == 0.7
    assert report["traffic"]["not_ok_rate"] == 0.1
    assert report["route_distribution_delta"] == {
        "fast": {"eval_rate": 0.5, "traffic_rate": 0.8, "delta": 0.3},
        "strong": {"eval_rate": 0.5, "traffic_rate": 0.2, "delta": -0.3},
    }
    assert report["route_bank_path"] == "examples/route_bank.sample.yaml"


def test_render_markdown_includes_actionable_quality_signals():
    report = {
        "route_bank_path": "examples/route_bank.sample.yaml",
        "eval": {
            "total": 2,
            "passed": 1,
            "failed": 1,
            "pass_rate": 0.5,
            "reasons": {"low_confidence": 2},
            "failures": [
                {
                    "expect": "strong",
                    "actual": "fast",
                    "target_model": "cheap-router",
                    "reason": "low_confidence",
                    "text": "分析这个 PR",
                }
            ],
        },
        "traffic": {
            "total": 10,
            "routes": {"fast": 8, "strong": 2},
            "reasons": {"low_confidence": 7},
            "low_confidence_rate": 0.7,
            "not_ok": 1,
            "not_ok_rate": 0.1,
        },
    }

    markdown = render_markdown(report)

    assert "# IntentMux Route Quality Report" in markdown
    assert "- pass_rate: 50.00%" in markdown
    assert "- low_confidence_rate: 70.00%" in markdown
    assert "分析这个 PR" in markdown


def test_main_writes_json_and_markdown(tmp_path: Path):
    eval_path = tmp_path / "eval.txt"
    summary_path = tmp_path / "summary.json"
    json_path = tmp_path / "report.json"
    md_path = tmp_path / "report.md"
    eval_path.write_text(
        "PASS\tfast\tfast\tcheap-router\tlow_confidence\t翻译成中文\n",
        encoding="utf-8",
    )
    summary_path.write_text(
        json.dumps({"total": 1, "routes": {"fast": 1}, "reasons": {"low_confidence": 1}}),
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            "scripts/route_quality_report.py",
            "--eval-output",
            str(eval_path),
            "--route-summary-json",
            str(summary_path),
            "--route-bank",
            "examples/route_bank.sample.yaml",
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
    assert payload["eval"]["total"] == 1
    assert md_path.read_text(encoding="utf-8").startswith("# IntentMux Route Quality Report")
