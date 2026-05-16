#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class EvalResult:
    total: int
    passed: int
    failed: int
    expected_routes: dict[str, int]
    actual_routes: dict[str, int]
    reasons: dict[str, int]
    failures: list[dict[str, str]]

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0


def parse_eval_output(output: str) -> EvalResult:
    passed = 0
    failed = 0
    expected_routes: Counter[str] = Counter()
    actual_routes: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    failures: list[dict[str, str]] = []

    for line in output.splitlines():
        parts = line.split("\t", 5)
        if len(parts) != 6 or parts[0] not in {"PASS", "FAIL"}:
            continue
        status, expect, actual, target_model, reason, text = parts
        expected_routes[expect] += 1
        actual_routes[actual] += 1
        reasons[reason] += 1
        if status == "PASS":
            passed += 1
        else:
            failed += 1
            failures.append(
                {
                    "expect": expect,
                    "actual": actual,
                    "target_model": target_model,
                    "reason": reason,
                    "text": text,
                }
            )

    return EvalResult(
        total=passed + failed,
        passed=passed,
        failed=failed,
        expected_routes=dict(expected_routes),
        actual_routes=dict(actual_routes),
        reasons=dict(reasons),
        failures=failures,
    )


def build_quality_report(
    *,
    eval_output: str,
    route_summary: dict[str, Any] | None,
    route_bank_path: str,
) -> dict[str, Any]:
    eval_result = parse_eval_output(eval_output)
    traffic = traffic_section(route_summary or {})
    return {
        "route_bank_path": route_bank_path,
        "eval": {
            "total": eval_result.total,
            "passed": eval_result.passed,
            "failed": eval_result.failed,
            "pass_rate": round(eval_result.pass_rate, 6),
            "expected_routes": eval_result.expected_routes,
            "actual_routes": eval_result.actual_routes,
            "reasons": eval_result.reasons,
            "failures": eval_result.failures,
        },
        "traffic": traffic,
        "route_distribution_delta": route_distribution_delta(
            eval_result.actual_routes,
            traffic.get("routes", {}),
        ),
    }


def build_quality_report_from_eval_json(
    *,
    eval_json: dict[str, Any],
    route_summary: dict[str, Any] | None,
    route_bank_path: str,
    margin: float | None = None,
) -> dict[str, Any]:
    cases = [case for case in eval_json.get("cases", []) if isinstance(case, dict)]
    total = len(cases)
    passed = sum(1 for case in cases if case.get("passed") is True)
    failed = sum(1 for case in cases if case.get("passed") is False)
    expected_routes = Counter(str(case.get("expect")) for case in cases if case.get("expect"))
    actual_routes = Counter(
        str(case.get("actual_route")) for case in cases if case.get("actual_route")
    )
    reasons = Counter(str(case.get("reason")) for case in cases if case.get("reason"))
    failures = [
        {
            "id": str(case.get("id") or ""),
            "slice": str(case.get("slice") or ""),
            "expect": str(case.get("expect") or ""),
            "actual": str(case.get("actual_route") or ""),
            "target_model": str(case.get("target_model") or ""),
            "reason": str(case.get("reason") or ""),
            "text": str(case.get("text") or ""),
        }
        for case in cases
        if case.get("passed") is False
    ]
    traffic = traffic_section(route_summary or {})
    eval_section = {
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": round(passed / total, 6) if total else 0.0,
        "expected_routes": dict(expected_routes),
        "actual_routes": dict(actual_routes),
        "reasons": dict(reasons),
        "failures": failures,
    }
    return {
        "route_bank_path": route_bank_path,
        "eval": eval_section,
        "traffic": traffic,
        "route_distribution_delta": route_distribution_delta(
            dict(actual_routes),
            traffic.get("routes", {}),
        ),
        "slice_metrics": slice_metrics(cases),
        "product_metrics": product_metrics(cases, margin=margin),
        "missing_decision_count": sum(1 for case in cases if not case.get("actual_route")),
    }


def slice_metrics(cases: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for case in cases:
        slice_name = case.get("slice")
        if not isinstance(slice_name, str) or not slice_name:
            slice_name = "unknown"
        grouped.setdefault(slice_name, []).append(case)

    metrics: dict[str, dict[str, Any]] = {}
    for slice_name, items in sorted(grouped.items()):
        total = len(items)
        passed = sum(1 for item in items if item.get("passed") is True)
        expected_routes = Counter(
            str(item.get("expect")) for item in items if item.get("expect")
        )
        actual_routes = Counter(
            str(item.get("actual_route")) for item in items if item.get("actual_route")
        )
        metrics[slice_name] = {
            "total": total,
            "passed": passed,
            "failed": sum(1 for item in items if item.get("passed") is False),
            "pass_rate": round(passed / total, 6) if total else 0.0,
            "expected_routes": dict(expected_routes),
            "actual_routes": dict(actual_routes),
        }
    return metrics


def product_metrics(
    cases: list[dict[str, Any]],
    *,
    margin: float | None,
) -> dict[str, float | int | None]:
    total = len(cases)
    lite_general = [case for case in cases if case.get("slice") == "lite_general_zh"]
    actual_lite = [case for case in cases if case.get("actual_route") == "lite"]
    high_risk = [case for case in cases if case.get("slice") == "high_risk_zh"]
    code = [case for case in cases if case.get("slice") == "deep_code_zh"]
    near_margin = near_margin_metrics(cases, margin)
    long_context = long_context_metrics(cases)
    return {
        "lite_general_keep_rate": route_rate(lite_general, "lite"),
        "lite_precision": expected_rate(actual_lite, "lite"),
        "deep_recall_high_risk": route_rate(high_risk, "deep"),
        "deep_recall_code": route_rate(code, "deep"),
        "low_confidence_rate": reason_rate(cases, "low_confidence"),
        "hard_rule_hit_rate": hard_rule_rate(cases),
        "deep_call_rate": route_rate(cases, "deep"),
        "near_margin_rate": near_margin["near_margin_rate"],
        "near_margin_measured_count": near_margin["near_margin_measured_count"],
        "near_margin_total_count": total,
        "long_context_total_count": long_context["total"],
        "long_context_measured_count": long_context["measured"],
        "long_context_schema_reserved_count": long_context["schema_reserved"],
        "long_context_missing_metadata_count": long_context["missing_metadata"],
    }


def route_rate(cases: list[dict[str, Any]], route: str) -> float:
    if not cases:
        return 0.0
    return sum(1 for case in cases if case.get("actual_route") == route) / len(cases)


def expected_rate(cases: list[dict[str, Any]], expected: str) -> float:
    if not cases:
        return 0.0
    return sum(1 for case in cases if case.get("expect") == expected) / len(cases)


def reason_rate(cases: list[dict[str, Any]], reason: str) -> float:
    if not cases:
        return 0.0
    return sum(1 for case in cases if case.get("reason") == reason) / len(cases)


def hard_rule_rate(cases: list[dict[str, Any]]) -> float:
    if not cases:
        return 0.0
    return sum(
        1
        for case in cases
        if isinstance(case.get("reason"), str)
        and str(case.get("reason")).startswith("hard_rule:")
    ) / len(cases)


def near_margin_rate(
    cases: list[dict[str, Any]],
    margin: float | None,
) -> float | None:
    return near_margin_metrics(cases, margin)["near_margin_rate"]


def near_margin_metrics(
    cases: list[dict[str, Any]],
    margin: float | None,
) -> dict[str, float | int | None]:
    if margin is None:
        return {"near_margin_rate": None, "near_margin_measured_count": 0}
    if not cases:
        return {"near_margin_rate": 0.0, "near_margin_measured_count": 0}
    near = 0
    measured = 0
    for case in cases:
        score = case.get("score")
        second_score = case.get("second_score")
        if not isinstance(score, int | float) or not isinstance(second_score, int | float):
            continue
        measured += 1
        if abs(float(score) - float(second_score)) <= margin:
            near += 1
    if measured == 0:
        return {"near_margin_rate": None, "near_margin_measured_count": 0}
    return {
        "near_margin_rate": near / measured,
        "near_margin_measured_count": measured,
    }


def long_context_metrics(cases: list[dict[str, Any]]) -> dict[str, int]:
    long_context = [
        case for case in cases if case.get("slice") == "deep_long_context_zh"
    ]
    measured = 0
    schema_reserved = 0
    missing_metadata = 0
    for case in long_context:
        policy = case.get("context_policy")
        if policy == "preserved_length":
            if isinstance(case.get("input_chars"), int) and isinstance(
                case.get("message_count"), int
            ):
                measured += 1
            else:
                missing_metadata += 1
        elif policy == "schema_reserved":
            schema_reserved += 1
        else:
            missing_metadata += 1
    return {
        "total": len(long_context),
        "measured": measured,
        "schema_reserved": schema_reserved,
        "missing_metadata": missing_metadata,
    }


def route_distribution_delta(
    eval_routes: dict[str, int],
    traffic_routes: dict[str, Any],
) -> dict[str, dict[str, float]]:
    eval_total = sum(eval_routes.values())
    traffic_int_routes = {
        route: int(count)
        for route, count in traffic_routes.items()
        if isinstance(route, str) and isinstance(count, int | float)
    }
    traffic_total = sum(traffic_int_routes.values())
    routes = sorted(set(eval_routes) | set(traffic_int_routes))
    return {
        route: {
            "eval_rate": round(eval_routes.get(route, 0) / eval_total, 6)
            if eval_total
            else 0.0,
            "traffic_rate": round(traffic_int_routes.get(route, 0) / traffic_total, 6)
            if traffic_total
            else 0.0,
            "delta": round(
                (
                    traffic_int_routes.get(route, 0) / traffic_total
                    if traffic_total
                    else 0.0
                )
                - (eval_routes.get(route, 0) / eval_total if eval_total else 0.0),
                6,
            ),
        }
        for route in routes
    }


def traffic_section(route_summary: dict[str, Any]) -> dict[str, Any]:
    total = int(route_summary.get("total") or 0)
    not_ok = int(route_summary.get("not_ok") or 0)
    reasons = dict_value(route_summary.get("reasons"))
    low_confidence = int(reasons.get("low_confidence", 0))
    return {
        "total": total,
        "routes": dict_value(route_summary.get("routes")),
        "targets": dict_value(route_summary.get("targets")),
        "reasons": reasons,
        "upstream_statuses": dict_value(route_summary.get("upstream_statuses")),
        "duration_percentiles_ms": dict_value(route_summary.get("duration_percentiles_ms")),
        "low_confidence_rate": round(low_confidence / total, 6) if total else 0.0,
        "not_ok": not_ok,
        "not_ok_rate": round(not_ok / total, 6) if total else 0.0,
    }


def dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def render_markdown(report: dict[str, Any]) -> str:
    eval_section = report["eval"]
    traffic = report["traffic"]
    lines = [
        "# IntentMux Route Quality Report",
        "",
        f"- route_bank: {report['route_bank_path']}",
        "",
        "## Eval",
        f"- total: {eval_section['total']}",
        f"- passed: {eval_section['passed']}",
        f"- failed: {eval_section['failed']}",
        f"- pass_rate: {eval_section['pass_rate']:.2%}",
        f"- reasons: {format_counts(eval_section.get('reasons', {}))}",
        "",
        "## Traffic",
        f"- total: {traffic['total']}",
        f"- routes: {format_counts(traffic.get('routes', {}))}",
        f"- reasons: {format_counts(traffic.get('reasons', {}))}",
        f"- low_confidence_rate: {traffic['low_confidence_rate']:.2%}",
        f"- not_ok_rate: {traffic['not_ok_rate']:.2%}",
    ]
    product = report.get("product_metrics", {})
    if product:
        lines.extend(["", "## Product Metrics"])
        for key, value in sorted(product.items()):
            if value is None:
                formatted = "n/a"
            elif key.endswith("_count"):
                formatted = str(int(value))
            else:
                formatted = f"{float(value):.2%}"
            lines.append(f"- {key}: {formatted}")
    slice_section = report.get("slice_metrics", {})
    if slice_section:
        lines.extend(["", "## Slice Metrics"])
        for slice_name, values in sorted(slice_section.items()):
            lines.append(
                "- "
                f"{slice_name}: total={values['total']} "
                f"pass_rate={values['pass_rate']:.2%} "
                f"actual={format_counts(values.get('actual_routes', {}))}"
            )
    delta = report.get("route_distribution_delta", {})
    if delta:
        lines.extend(["", "## Route Distribution Delta"])
        for route, values in sorted(delta.items()):
            lines.append(
                "- "
                f"{route}: eval={values['eval_rate']:.2%} "
                f"traffic={values['traffic_rate']:.2%} "
                f"delta={values['delta']:.2%}"
            )
    failures = eval_section.get("failures", [])
    if failures:
        lines.extend(["", "## Eval Failures"])
        for failure in failures:
            lines.append(
                "- "
                f"expect={failure['expect']} actual={failure['actual']} "
                f"target={failure['target_model']} reason={failure['reason']} "
                f"text={failure['text']}"
            )
    lines.append("")
    return "\n".join(lines)


def format_counts(counts: dict[str, Any]) -> str:
    if not counts:
        return "none"
    return ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-output", help="Text output from scripts/eval_routes.py")
    parser.add_argument("--eval-json", help="JSON output from scripts/eval_routes.py --json-output")
    parser.add_argument("--route-summary-json", help="JSON output from scripts/router_log_summary.py --json")
    parser.add_argument("--route-bank", default="examples/route_bank.sample.yaml")
    parser.add_argument("--margin", type=float, default=None)
    parser.add_argument("--json-output", required=True)
    parser.add_argument("--markdown-output", required=True)
    args = parser.parse_args()

    route_summary = None
    if args.route_summary_json:
        route_summary = json.loads(Path(args.route_summary_json).read_text(encoding="utf-8"))
    if args.eval_json:
        report = build_quality_report_from_eval_json(
            eval_json=json.loads(Path(args.eval_json).read_text(encoding="utf-8")),
            route_summary=route_summary,
            route_bank_path=args.route_bank,
            margin=args.margin,
        )
    elif args.eval_output:
        eval_output = Path(args.eval_output).read_text(encoding="utf-8")
        report = build_quality_report(
            eval_output=eval_output,
            route_summary=route_summary,
            route_bank_path=args.route_bank,
        )
    else:
        raise SystemExit("--eval-output or --eval-json is required")
    Path(args.json_output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    Path(args.markdown_output).write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"json": args.json_output, "markdown": args.markdown_output}))


if __name__ == "__main__":
    main()
