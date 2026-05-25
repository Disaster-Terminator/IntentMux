#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.route_quality_report import (  # noqa: E402
    baseline_summary_from_eval_json,
    product_metrics,
    slice_metrics,
)
from router.config import load_settings  # noqa: E402

DEFAULT_BASELINES = (
    "current-router",
    "always-lite",
    "always-deep",
    "hard-rule-only",
    "embedding-only",
)
DEFAULT_THRESHOLDS = (0.3, 0.35, 0.4, 0.45, 0.5, 0.55)


def parse_alphas(value: str) -> list[float]:
    if not value.strip():
        return []
    alphas = [float(item.strip()) for item in value.split(",") if item.strip()]
    for alpha in alphas:
        if alpha <= 0:
            raise ValueError("alphas must be greater than 0")
        if alpha > 1:
            raise ValueError("alphas must be at most 1")
    return sorted(set(alphas))


def parse_thresholds(value: str) -> list[float]:
    thresholds = [float(item.strip()) for item in value.split(",") if item.strip()]
    if not thresholds:
        raise ValueError("thresholds must contain at least one value")
    return sorted(set(thresholds))


def safe_label(label: str) -> str:
    return (
        label.replace(":", "-")
        .replace("/", "-")
        .replace("\\", "-")
        .replace(".", "p")
    )


def run_eval_json(
    *,
    cases: Path,
    routes: Path,
    baseline: str,
    output: Path,
    mock_embeddings: bool,
    threshold: float | None = None,
    margin: float | None = None,
    env_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "scripts/eval_routes.py",
        "--cases",
        str(cases),
        "--routes",
        str(routes),
        "--baseline",
        baseline,
        "--json-output",
        str(output),
    ]
    if mock_embeddings:
        cmd.append("--mock-embeddings")
    if threshold is not None:
        cmd.extend(["--threshold", str(threshold)])
    if margin is not None:
        cmd.extend(["--margin", str(margin)])

    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)

    result = subprocess.run(cmd, text=True, capture_output=True, check=False, env=env)
    return {
        "cmd": " ".join(cmd),
        "exit_code": result.returncode,
        "json": str(output),
        "stdout_tail": result.stdout[-1000:],
        "stderr_tail": result.stderr[-1000:],
    }


def summarize_eval(label: str, payload: dict[str, Any], exit_code: int | None = None) -> dict[str, Any]:
    cases = [case for case in payload.get("cases", []) if isinstance(case, dict)]
    total = len(cases)
    actual_routes = Counter(
        str(case.get("actual_route")) for case in cases if case.get("actual_route")
    )
    slices = sorted(
        {str(case.get("slice")) for case in cases if isinstance(case.get("slice"), str)}
    )
    summary = baseline_summary_from_eval_json(
        label,
        payload,
        margin=payload.get("margin") if isinstance(payload.get("margin"), int | float) else None,
    )
    summary["exit_code"] = exit_code
    summary["lite_call_rate"] = round(actual_routes.get("lite", 0) / total, 6) if total else 0.0
    summary["slices"] = slices
    summary["slice_metrics"] = summarize_slices(cases)
    summary["route_quality_slice_metrics"] = slice_metrics(cases)
    summary["product_metrics"] = product_metrics(
        cases,
        margin=payload.get("margin") if isinstance(payload.get("margin"), int | float) else None,
    )
    return summary


def simulated_exit_code(payload: dict[str, Any]) -> int:
    cases = [case for case in payload.get("cases", []) if isinstance(case, dict)]
    return 0 if all(case.get("passed") is True for case in cases) else 1


def simulate_threshold_payload(
    *,
    scoring_payload: dict[str, Any],
    threshold: float,
    margin: float,
    fallback_route_id: str,
    label: str,
) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for raw_case in scoring_payload.get("cases", []):
        if not isinstance(raw_case, dict):
            continue
        case = dict(raw_case)
        reason = str(case.get("reason") or "")
        score = case.get("score")
        second_score = case.get("second_score")
        if reason == "embedding" and isinstance(score, int | float):
            measured_second_score = (
                float(second_score) if isinstance(second_score, int | float) else 0.0
            )
            if float(score) < threshold or float(score) - measured_second_score < margin:
                case["actual_route"] = fallback_route_id
                case["reason"] = "low_confidence"
                case["target_model"] = fallback_route_id
            case["passed"] = case.get("actual_route") == case.get("expect")
        cases.append(case)
    return {
        "schema": scoring_payload.get("schema", "intentmux-route-eval-v1"),
        "baseline": label,
        "threshold": threshold,
        "margin": margin,
        "cases": cases,
    }


def summarize_slices(cases: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for case in cases:
        name = case.get("slice")
        if not isinstance(name, str) or not name:
            name = "unknown"
        grouped.setdefault(name, []).append(case)

    summary: dict[str, dict[str, Any]] = {}
    for name, items in sorted(grouped.items()):
        total = len(items)
        passed = sum(1 for item in items if item.get("passed") is True)
        actual_routes = Counter(
            str(item.get("actual_route")) for item in items if item.get("actual_route")
        )
        summary[name] = {
            "total": total,
            "pass_rate": round(passed / total, 6) if total else 0.0,
            "deep_call_rate": round(actual_routes.get("deep", 0) / total, 6)
            if total
            else 0.0,
            "actual_routes": dict(actual_routes),
        }
    return summary


def build_report(
    *,
    eval_payloads: dict[str, dict[str, Any]],
    run_results: dict[str, dict[str, Any]],
    threshold_labels: list[str],
    alpha_labels: list[str],
    cases_path: Path,
    routes_path: Path,
) -> dict[str, Any]:
    summaries = {
        label: summarize_eval(
            label,
            payload,
            exit_code=run_results.get(label, {}).get("exit_code"),
        )
        for label, payload in eval_payloads.items()
    }
    curve = [summaries[label] for label in threshold_labels if label in summaries]
    alpha_curve = [summaries[label] for label in alpha_labels if label in summaries]
    primary_payload = eval_payloads.get("current-router") or next(
        iter(eval_payloads.values()),
        {"cases": []},
    )
    return {
        "schema": "intentmux-route-calibration-v1",
        "cases_path": str(cases_path),
        "routes_path": str(routes_path),
        "margin": primary_payload.get("margin"),
        "thresholds": [
            payload.get("threshold")
            for label, payload in eval_payloads.items()
            if label in threshold_labels
        ],
        "coverage": coverage(primary_payload),
        "baselines": {
            label: summaries[label]
            for label in DEFAULT_BASELINES
            if label in summaries
        },
        "threshold_curve": curve,
        "alpha_curve": alpha_curve,
        "runs": run_results,
        "recommendation": recommendation(summaries, curve, alpha_curve),
    }


def coverage(payload: dict[str, Any]) -> dict[str, Any]:
    cases = [case for case in payload.get("cases", []) if isinstance(case, dict)]
    languages: Counter[str] = Counter()
    slices: Counter[str] = Counter()
    for case in cases:
        text = str(case.get("text") or "")
        slice_name = case.get("slice")
        if not isinstance(slice_name, str) or not slice_name:
            slice_name = "unknown"
        language = infer_language(text)
        if language == "unknown":
            language = infer_language_from_slice(slice_name)
        languages[language] += 1
        slices[slice_name] += 1
    return {
        "total": len(cases),
        "languages": dict(languages),
        "slices": dict(slices),
        "bilingual_sample_count": sum(
            count for language, count in languages.items() if language in {"zh", "en"}
        ),
    }


def infer_language(text: str) -> str:
    if any("\u4e00" <= char <= "\u9fff" for char in text):
        return "zh"
    ascii_letters = sum(1 for char in text if char.isascii() and char.isalpha())
    if ascii_letters:
        return "en"
    return "unknown"


def infer_language_from_slice(slice_name: str) -> str:
    parts = slice_name.split("_")
    for part in reversed(parts):
        if part in {"zh", "en"}:
            return part
    return "unknown"


def recommendation(
    summaries: dict[str, dict[str, Any]],
    curve: list[dict[str, Any]],
    alpha_curve: list[dict[str, Any]],
) -> dict[str, Any]:
    current = summaries.get("current-router")
    if not current:
        return {
            "status": "blocked",
            "reason": "current-router summary is missing",
        }
    useful_curve = [
        point
        for point in curve
        if point.get("total") == current.get("total")
        and point.get("exit_code") is not None
    ]
    if not useful_curve:
        return {
            "status": "blocked",
            "reason": "threshold curve is missing",
        }
    best = max(
        useful_curve,
        key=lambda point: (float(point["pass_rate"]), -float(point["deep_call_rate"])),
    )
    result = {
        "status": "evidence_ready",
        "next_step": "Use this report to judge scorer or route-bank changes before changing production routing.",
        "current_pass_rate": current["pass_rate"],
        "current_deep_call_rate": current["deep_call_rate"],
        "best_threshold_label": best["label"],
        "best_threshold_pass_rate": best["pass_rate"],
        "best_threshold_deep_call_rate": best["deep_call_rate"],
    }
    useful_alpha_curve = [
        point
        for point in alpha_curve
        if point.get("total") == current.get("total")
        and point.get("exit_code") is not None
    ]
    if useful_alpha_curve:
        best_alpha = max(
            useful_alpha_curve,
            key=lambda point: (float(point["pass_rate"]), -float(point["deep_call_rate"])),
        )
        result.update(
            {
                "best_alpha_label": best_alpha["label"],
                "best_alpha_pass_rate": best_alpha["pass_rate"],
                "best_alpha_deep_call_rate": best_alpha["deep_call_rate"],
            }
        )
    return result


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# IntentMux Route Calibration Report",
        "",
        f"- cases: {report['cases_path']}",
        f"- routes: {report['routes_path']}",
        f"- recommendation: {report['recommendation']['status']}",
        "",
        "## Baseline Comparison",
    ]
    for label, summary in report["baselines"].items():
        lines.append(
            "- "
            f"{label}: pass_rate={summary['pass_rate']:.2%} "
            f"deep_call_rate={summary['deep_call_rate']:.2%} "
            f"exit_code={summary['exit_code']}"
        )
    lines.extend(["", "## Threshold Curve"])
    for point in report["threshold_curve"]:
        lines.append(
            "- "
            f"{point['label']}: pass_rate={point['pass_rate']:.2%} "
            f"deep_call_rate={point['deep_call_rate']:.2%} "
            f"exit_code={point['exit_code']}"
        )
    lines.extend(["", "## Alpha Curve"])
    alpha_curve = report.get("alpha_curve", [])
    if alpha_curve:
        for point in alpha_curve:
            lines.append(
                "- "
                f"{point['label']}: pass_rate={point['pass_rate']:.2%} "
                f"deep_call_rate={point['deep_call_rate']:.2%} "
                f"exit_code={point['exit_code']}"
            )
    else:
        lines.append("- not_run")
    lines.extend(["", "## Slice Metrics"])
    current = report["baselines"].get("current-router", {})
    for slice_name, values in sorted(current.get("slice_metrics", {}).items()):
        lines.append(
            "- "
            f"{slice_name}: total={values['total']} "
            f"pass_rate={values['pass_rate']:.2%} "
            f"deep_call_rate={values['deep_call_rate']:.2%}"
        )
    coverage_section = report.get("coverage", {})
    lines.extend(
        [
            "",
            "## Coverage",
            f"- total: {coverage_section.get('total', 0)}",
            f"- languages: {format_counts(coverage_section.get('languages', {}))}",
            f"- slices: {format_counts(coverage_section.get('slices', {}))}",
            f"- bilingual_sample_count: {coverage_section.get('bilingual_sample_count', 0)}",
            "",
            "## Recommendation",
            f"- status: {report['recommendation']['status']}",
        ]
    )
    if report["recommendation"].get("best_threshold_label"):
        lines.append(
            "- best_observed_threshold: "
            f"{report['recommendation']['best_threshold_label']} "
            f"pass_rate={report['recommendation']['best_threshold_pass_rate']:.2%} "
            f"deep_call_rate={report['recommendation']['best_threshold_deep_call_rate']:.2%}"
        )
    if report["recommendation"].get("best_alpha_label"):
        lines.append(
            "- best_observed_alpha: "
            f"{report['recommendation']['best_alpha_label']} "
            f"pass_rate={report['recommendation']['best_alpha_pass_rate']:.2%} "
            f"deep_call_rate={report['recommendation']['best_alpha_deep_call_rate']:.2%}"
        )
    lines.append("")
    return "\n".join(lines)


def format_counts(counts: Any) -> str:
    if not isinstance(counts, dict) or not counts:
        return "none"
    return ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default="examples/eval_bank.sample.yaml")
    parser.add_argument("--routes", default="config/routes.yaml")
    parser.add_argument("--work-dir", default=".intentmux-home/quality-spikes/latest")
    parser.add_argument("--json-output")
    parser.add_argument("--markdown-output")
    parser.add_argument(
        "--thresholds",
        default=",".join(str(item) for item in DEFAULT_THRESHOLDS),
        help="Comma-separated thresholds for current-router curve.",
    )
    parser.add_argument("--margin", type=float)
    parser.add_argument(
        "--alphas",
        default="",
        help=(
            "Comma-separated Aurelio hybrid alpha values to evaluate with "
            "ROUTER_AURELIO_HYBRID_ALPHA. Empty by default to avoid extra daily work."
        ),
    )
    parser.add_argument("--mock-embeddings", action="store_true")
    args = parser.parse_args()

    cases = Path(args.cases)
    routes = Path(args.routes)
    work_dir = Path(args.work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    eval_payloads: dict[str, dict[str, Any]] = {}
    run_results: dict[str, dict[str, Any]] = {}
    settings = load_settings(routes)
    margin = settings.margin if args.margin is None else args.margin
    for baseline in DEFAULT_BASELINES:
        output = work_dir / f"eval-{safe_label(baseline)}.json"
        run_results[baseline] = run_eval_json(
            cases=cases,
            routes=routes,
            baseline=baseline,
            output=output,
            mock_embeddings=args.mock_embeddings,
            margin=margin,
        )
        if output.exists():
            eval_payloads[baseline] = json.loads(output.read_text(encoding="utf-8"))

    scoring_probe_label = "threshold-scoring-probe"
    scoring_probe_output = work_dir / f"eval-{safe_label(scoring_probe_label)}.json"
    run_results[scoring_probe_label] = run_eval_json(
        cases=cases,
        routes=routes,
        baseline="current-router",
        output=scoring_probe_output,
        mock_embeddings=args.mock_embeddings,
        threshold=0.0,
        margin=0.0,
    )
    scoring_payload = (
        json.loads(scoring_probe_output.read_text(encoding="utf-8"))
        if scoring_probe_output.exists()
        else {"cases": []}
    )

    threshold_labels: list[str] = []
    for threshold in parse_thresholds(args.thresholds):
        label = f"threshold:{threshold:g}"
        threshold_labels.append(label)
        output = work_dir / f"eval-{safe_label(label)}.json"
        payload = simulate_threshold_payload(
            scoring_payload=scoring_payload,
            threshold=threshold,
            margin=margin,
            fallback_route_id=settings.fallback_route_id,
            label=label,
        )
        output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        run_results[label] = {
            "mode": "simulated_from_threshold_scoring_probe",
            "probe_json": str(scoring_probe_output),
            "exit_code": simulated_exit_code(payload),
            "json": str(output),
        }
        eval_payloads[label] = payload

    alpha_labels: list[str] = []
    for alpha in parse_alphas(args.alphas):
        label = f"alpha:{alpha:g}"
        alpha_labels.append(label)
        output = work_dir / f"eval-{safe_label(label)}.json"
        run_results[label] = run_eval_json(
            cases=cases,
            routes=routes,
            baseline="current-router",
            output=output,
            mock_embeddings=args.mock_embeddings,
            margin=margin,
            env_overrides={"ROUTER_AURELIO_HYBRID_ALPHA": str(alpha)},
        )
        if output.exists():
            payload = json.loads(output.read_text(encoding="utf-8"))
            payload["baseline"] = label
            payload["aurelio_hybrid_alpha"] = alpha
            output.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            eval_payloads[label] = payload

    report = build_report(
        eval_payloads=eval_payloads,
        run_results=run_results,
        threshold_labels=threshold_labels,
        alpha_labels=alpha_labels,
        cases_path=cases,
        routes_path=routes,
    )
    json_path = Path(args.json_output) if args.json_output else work_dir / "route-calibration-report.json"
    md_path = (
        Path(args.markdown_output)
        if args.markdown_output
        else work_dir / "route-calibration-report.md"
    )
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"json": str(json_path), "markdown": str(md_path)}))


if __name__ == "__main__":
    main()
