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
    parser.add_argument("--eval-output", required=True, help="Text output from scripts/eval_routes.py")
    parser.add_argument("--route-summary-json", help="JSON output from scripts/router_log_summary.py --json")
    parser.add_argument("--route-bank", default="examples/route_bank.sample.yaml")
    parser.add_argument("--json-output", required=True)
    parser.add_argument("--markdown-output", required=True)
    args = parser.parse_args()

    eval_output = Path(args.eval_output).read_text(encoding="utf-8")
    route_summary = None
    if args.route_summary_json:
        route_summary = json.loads(Path(args.route_summary_json).read_text(encoding="utf-8"))
    report = build_quality_report(
        eval_output=eval_output,
        route_summary=route_summary,
        route_bank_path=args.route_bank,
    )
    Path(args.json_output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    Path(args.markdown_output).write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"json": args.json_output, "markdown": args.markdown_output}))


if __name__ == "__main__":
    main()
