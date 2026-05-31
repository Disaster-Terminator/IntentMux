#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.route_quality_report import (  # noqa: E402
    baseline_summary_from_eval_json,
    format_counts,
    load_labeled_eval_jsons,
)


def case_ids(eval_json: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for index, case in enumerate(eval_json.get("cases", []), start=1):
        if not isinstance(case, dict):
            continue
        case_id = case.get("id")
        if isinstance(case_id, str) and case_id:
            ids.append(case_id)
            continue
        text_sha256 = case.get("text_sha256")
        if isinstance(text_sha256, str) and text_sha256:
            ids.append(f"sha256:{text_sha256}")
            continue
        ids.append(f"row:{index}")
    return ids


def build_threshold_sweep_report(
    labeled_eval_jsons: list[tuple[str, dict[str, Any]]],
    *,
    false_lite_weight: float = 10.0,
    false_deep_weight: float = 1.0,
) -> dict[str, Any]:
    if not labeled_eval_jsons:
        raise ValueError("at least one eval JSON is required")

    reference_ids = case_ids(labeled_eval_jsons[0][1])
    for label, payload in labeled_eval_jsons[1:]:
        if case_ids(payload) != reference_ids:
            raise ValueError(
                f"{label} does not use the same eval case set as "
                f"{labeled_eval_jsons[0][0]}"
            )

    candidates = [
        baseline_summary_from_eval_json(
            label,
            payload,
            false_lite_weight=false_lite_weight,
            false_deep_weight=false_deep_weight,
        )
        for label, payload in labeled_eval_jsons
    ]
    candidates.sort(
        key=lambda item: (
            float(item.get("weighted_route_cost") or 0.0),
            -float(item.get("pass_rate") or 0.0),
            float(item.get("deep_call_rate") or 0.0),
            str(item.get("label") or ""),
        )
    )
    return {
        "schema": "intentmux-threshold-sweep-v1",
        "case_count": len(reference_ids),
        "false_lite_weight": false_lite_weight,
        "false_deep_weight": false_deep_weight,
        "recommended_candidate": candidates[0]["label"] if candidates else None,
        "candidates": candidates,
    }


def build_threshold_sweep_from_source(
    source_eval_json: dict[str, Any],
    *,
    thresholds: list[float],
    margin: float,
    fallback_route_id: str = "lite",
    false_lite_weight: float = 10.0,
    false_deep_weight: float = 1.0,
) -> dict[str, Any]:
    if not thresholds:
        raise ValueError("at least one threshold is required")
    labeled = [
        (
            threshold_label(threshold),
            sweep_eval_payload(
                source_eval_json,
                threshold=threshold,
                margin=margin,
                fallback_route_id=fallback_route_id,
            ),
        )
        for threshold in thresholds
    ]
    return build_threshold_sweep_report(
        labeled,
        false_lite_weight=false_lite_weight,
        false_deep_weight=false_deep_weight,
    )


def sweep_eval_payload(
    source_eval_json: dict[str, Any],
    *,
    threshold: float,
    margin: float,
    fallback_route_id: str = "lite",
) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for source_case in source_eval_json.get("cases", []):
        if not isinstance(source_case, dict):
            continue
        case = redacted_case_copy(source_case)
        actual_route, reason = route_for_threshold(
            source_case,
            threshold=threshold,
            margin=margin,
            fallback_route_id=fallback_route_id,
        )
        case["actual_route"] = actual_route
        case["reason"] = reason
        expect = case.get("expect")
        case["passed"] = bool(expect and actual_route == expect)
        cases.append(case)
    return {
        "schema": "intentmux-route-eval-v1",
        "baseline": threshold_label(threshold),
        "threshold": threshold,
        "margin": margin,
        "cases": cases,
    }


def redacted_case_copy(source_case: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = {
        "id",
        "baseline",
        "slice",
        "text_sha256",
        "text_chars",
        "expect",
        "score",
        "second_score",
        "score_margin",
        "top_route_id",
        "second_route_id",
        "match_source",
        "match_index",
        "match_text_sha256",
        "match_score",
        "match_provenance",
        "input_chars",
        "message_count",
        "context_policy",
    }
    return {key: value for key, value in source_case.items() if key in allowed_keys}


def route_for_threshold(
    case: dict[str, Any],
    *,
    threshold: float,
    margin: float,
    fallback_route_id: str,
) -> tuple[str, str]:
    reason = case.get("reason")
    if isinstance(reason, str) and reason.startswith(("hard_rule:", "explicit")):
        actual_route = case.get("actual_route")
        if isinstance(actual_route, str) and actual_route:
            return actual_route, reason

    score = case.get("score")
    score_margin = case.get("score_margin")
    top_route_id = case.get("top_route_id")
    if (
        isinstance(score, int | float)
        and isinstance(score_margin, int | float)
        and isinstance(top_route_id, str)
        and top_route_id
    ):
        if float(score) >= threshold and float(score_margin) >= margin:
            return top_route_id, "sweep:embedding"
        return fallback_route_id, "sweep:low_confidence"

    actual_route = case.get("actual_route")
    if isinstance(actual_route, str) and actual_route:
        return actual_route, str(reason or "sweep:unchanged")
    return fallback_route_id, "sweep:missing_decision"


def threshold_label(threshold: float) -> str:
    return f"threshold-{threshold:.2f}"


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# IntentMux Threshold Sweep Report",
        "",
        f"- case_count: {report['case_count']}",
        f"- false_lite_weight: {report['false_lite_weight']}",
        f"- false_deep_weight: {report['false_deep_weight']}",
        f"- recommended_candidate: {report['recommended_candidate']}",
        "",
        "## Candidates",
    ]
    for item in report.get("candidates", []):
        lines.append(
            "- "
            f"{item['label']}: "
            f"threshold={format_optional_float(item.get('threshold'))} "
            f"pass_rate={item['pass_rate']:.2%} "
            f"deep_call_rate={item['deep_call_rate']:.2%} "
            f"false_lite={item['false_lite_count']} "
            f"false_deep={item['false_deep_count']} "
            f"weighted_route_cost={item['weighted_route_cost']:.3f} "
            f"actual={format_counts(item.get('actual_routes', {}))}"
        )
    lines.append("")
    return "\n".join(lines)


def format_optional_float(value: Any) -> str:
    if isinstance(value, int | float):
        return f"{float(value):.4g}"
    return "n/a"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--eval-json",
        action="append",
        help=(
            "JSON output from scripts/eval_routes.py --json-output. "
            "May be repeated as label=/path/to/eval.json."
        ),
    )
    parser.add_argument(
        "--source-eval-json",
        help=(
            "Single eval JSON to re-score offline for each --threshold using "
            "stored score/top_route_id fields."
        ),
    )
    parser.add_argument(
        "--threshold",
        action="append",
        type=float,
        help="Threshold candidate for --source-eval-json mode. May be repeated.",
    )
    parser.add_argument("--margin", type=float, default=0.04)
    parser.add_argument("--fallback-route-id", default="lite")
    parser.add_argument("--false-lite-weight", type=float, default=10.0)
    parser.add_argument("--false-deep-weight", type=float, default=1.0)
    parser.add_argument("--json-output", required=True)
    parser.add_argument("--markdown-output", required=True)
    args = parser.parse_args()

    if args.source_eval_json:
        source = json.loads(Path(args.source_eval_json).read_text(encoding="utf-8"))
        report = build_threshold_sweep_from_source(
            source,
            thresholds=args.threshold or [],
            margin=args.margin,
            fallback_route_id=args.fallback_route_id,
            false_lite_weight=args.false_lite_weight,
            false_deep_weight=args.false_deep_weight,
        )
    elif args.eval_json:
        report = build_threshold_sweep_report(
            load_labeled_eval_jsons(args.eval_json),
            false_lite_weight=args.false_lite_weight,
            false_deep_weight=args.false_deep_weight,
        )
    else:
        raise SystemExit("--source-eval-json or --eval-json is required")
    Path(args.json_output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    Path(args.markdown_output).write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"json": args.json_output, "markdown": args.markdown_output}))


if __name__ == "__main__":
    main()
