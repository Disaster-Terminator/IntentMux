from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import json
from typing import Any, Iterable

try:
    from scripts.router_log_summary import (
        ParseDiagnostics,
        iter_lines,
        ok_from_record,
        outcome_from_record,
        parse_route_records,
    )
except ModuleNotFoundError:
    from router_log_summary import (
        ParseDiagnostics,
        iter_lines,
        ok_from_record,
        outcome_from_record,
        parse_route_records,
    )


@dataclass(frozen=True)
class BudgetConfig:
    min_total: int = 1
    max_error_rate: float = 0.0
    max_target_error_rate: float = 0.0
    max_not_ok_rate: float | None = None
    max_route_error_rate: float | dict[str, float] | None = None
    max_reason_rates: dict[str, float] | None = None
    max_upstream_status_rates: dict[str, float] | None = None
    max_malformed_json: int | None = None
    max_missing_event: int | None = None
    max_unknown_event: int | None = None
    max_ignored_records: int | None = None


@dataclass(frozen=True)
class BudgetResult:
    passed: bool
    total: int
    completed: int
    errors: int
    error_rate: float
    not_ok: int
    not_ok_rate: float
    target_error_rates: dict[str, float]
    route_error_rates: dict[str, float]
    reason_rates: dict[str, float]
    outcome_rates: dict[str, float]
    upstream_status_rates: dict[str, float]
    error_types: dict[str, int]
    reasons: list[str]
    parse_diagnostics: ParseDiagnostics
    ignored_records: int


def check_budget(
    records: Iterable[dict[str, Any]],
    config: BudgetConfig,
    parse_diagnostics: ParseDiagnostics | None = None,
) -> BudgetResult:
    total = 0
    completed = 0
    errors = 0
    target_totals: Counter[str] = Counter()
    target_errors: Counter[str] = Counter()
    route_totals: Counter[str] = Counter()
    route_errors: Counter[str] = Counter()
    reason_totals: Counter[str] = Counter()
    upstream_status_totals: Counter[str] = Counter()
    outcome_totals: Counter[str] = Counter()
    error_types: Counter[str] = Counter()
    not_ok = 0

    for record in records:
        total += 1
        if not ok_from_record(record):
            not_ok += 1
        outcome_totals[outcome_from_record(record)] += 1
        target_model = record.get("target_model")
        route_id = record.get("route_id")
        if isinstance(target_model, str):
            target_totals[target_model] += 1
        route_key = route_id if isinstance(route_id, str) and route_id else "unknown"
        route_totals[route_key] += 1
        reason = record.get("reason")
        if isinstance(reason, str):
            reason_totals[reason] += 1
        upstream_status = record.get("upstream_status")
        if isinstance(upstream_status, int):
            upstream_status_totals[str(upstream_status)] += 1

        event = record.get("event")
        if event == "route_complete":
            completed += 1
        elif event == "route_error":
            errors += 1
            if isinstance(target_model, str):
                target_errors[target_model] += 1
            route_errors[route_key] += 1
            error_type = record.get("error_type")
            if isinstance(error_type, str):
                error_types[error_type] += 1

    error_rate = errors / total if total else 0.0
    not_ok_rate = not_ok / total if total else 0.0
    target_error_rates = {
        target: target_errors[target] / target_total
        for target, target_total in target_totals.items()
    }
    route_error_rates = {
        route: route_errors[route] / route_total
        for route, route_total in route_totals.items()
    }
    reason_rates = {
        reason: reason_total / total for reason, reason_total in reason_totals.items()
    }
    outcome_rates = {
        outcome: outcome_total / total
        for outcome, outcome_total in outcome_totals.items()
    }
    upstream_status_rates = {
        status: status_total / total
        for status, status_total in upstream_status_totals.items()
    }

    reasons: list[str] = []
    if total < config.min_total:
        reasons.append(f"total {total} below min_total {config.min_total}")
    if error_rate > config.max_error_rate:
        reasons.append(
            f"error_rate {error_rate:.4f} exceeds max_error_rate {config.max_error_rate:.4f}"
        )
    if config.max_not_ok_rate is not None and not_ok_rate > config.max_not_ok_rate:
        reasons.append(
            f"not_ok_rate {not_ok_rate:.4f} exceeds max_not_ok_rate {config.max_not_ok_rate:.4f}"
        )
    for target, target_error_rate in sorted(target_error_rates.items()):
        if target_error_rate > config.max_target_error_rate:
            reasons.append(
                f"target {target} error_rate {target_error_rate:.4f} "
                f"exceeds max_target_error_rate {config.max_target_error_rate:.4f}"
            )
    route_budget = config.max_route_error_rate
    if isinstance(route_budget, dict):
        default_route_budget = route_budget.get("*")
        if isinstance(default_route_budget, float):
            for route, route_error_rate in sorted(route_error_rates.items()):
                if route_error_rate > default_route_budget:
                    reasons.append(
                        f"route {route} error_rate {route_error_rate:.4f} "
                        f"exceeds max_route_error_rate {default_route_budget:.4f}"
                    )
        for route, max_route_rate in sorted(route_budget.items()):
            if route == "*":
                continue
            route_error_rate = route_error_rates.get(route, 0.0)
            if route_error_rate > max_route_rate:
                reasons.append(
                    f"route {route} error_rate {route_error_rate:.4f} "
                    f"exceeds max_route_error_rate {max_route_rate:.4f}"
                )
    elif route_budget is not None:
        for route, route_error_rate in sorted(route_error_rates.items()):
            if route_error_rate > route_budget:
                reasons.append(
                    f"route {route} error_rate {route_error_rate:.4f} "
                    f"exceeds max_route_error_rate {route_budget:.4f}"
                )
    for reason, max_reason_rate in sorted((config.max_reason_rates or {}).items()):
        reason_rate = reason_rates.get(reason, 0.0)
        if reason_rate > max_reason_rate:
            reasons.append(
                f"reason {reason} rate {reason_rate:.4f} "
                f"exceeds max_reason_rate {max_reason_rate:.4f}"
            )
    for status, max_status_rate in sorted(
        (config.max_upstream_status_rates or {}).items()
    ):
        status_rate = upstream_status_rates.get(status, 0.0)
        if status_rate > max_status_rate:
            reasons.append(
                f"upstream_status {status} rate {status_rate:.4f} "
                f"exceeds max_upstream_status_rate {max_status_rate:.4f}"
            )
    diagnostics = parse_diagnostics or ParseDiagnostics()
    diagnostics_budgets = (
        ("malformed_json", diagnostics.malformed_json_lines, config.max_malformed_json),
        ("missing_event", diagnostics.missing_event_records, config.max_missing_event),
        ("unknown_event", diagnostics.unknown_event_records, config.max_unknown_event),
    )
    for name, count, max_count in diagnostics_budgets:
        if max_count is not None and count > max_count:
            reasons.append(f"{name} {count} exceeds max_{name} {max_count}")

    ignored_records = (
        diagnostics.malformed_json_lines
        + diagnostics.missing_event_records
        + diagnostics.unknown_event_records
    )
    if (
        config.max_ignored_records is not None
        and ignored_records > config.max_ignored_records
    ):
        reasons.append(
            f"ignored_records {ignored_records} exceeds "
            f"max_ignored_records {config.max_ignored_records}"
        )

    return BudgetResult(
        passed=not reasons,
        total=total,
        completed=completed,
        errors=errors,
        error_rate=error_rate,
        not_ok=not_ok,
        not_ok_rate=not_ok_rate,
        target_error_rates=target_error_rates,
        route_error_rates=route_error_rates,
        reason_rates=reason_rates,
        outcome_rates=outcome_rates,
        upstream_status_rates=upstream_status_rates,
        error_types=dict(error_types),
        reasons=reasons,
        parse_diagnostics=diagnostics,
        ignored_records=ignored_records,
    )


def format_budget_result(result: BudgetResult) -> str:
    status = "PASS" if result.passed else "FAIL"
    lines = [
        f"{status} route_error_budget",
        (
            f"total={result.total} completed={result.completed} "
            f"errors={result.errors} error_rate={result.error_rate:.4f} "
            f"not_ok={result.not_ok} not_ok_rate={result.not_ok_rate:.4f}"
        ),
        f"target_error_rates: {format_rates(result.target_error_rates)}",
        f"route_error_rates: {format_rates(result.route_error_rates)}",
        f"reason_rates: {format_rates(result.reason_rates)}",
        f"outcome_rates: {format_rates(result.outcome_rates)}",
        f"upstream_status_rates: {format_rates(result.upstream_status_rates)}",
        f"error_types: {format_counts(result.error_types)}",
    ]
    if result.reasons:
        lines.append(f"reasons: {'; '.join(result.reasons)}")
    diag = result.parse_diagnostics
    if any(
        (
            diag.malformed_json_lines,
            diag.missing_event_records,
            diag.unknown_event_records,
        )
    ):
        lines.append(
            "parse_diagnostics: "
            f"malformed_json={diag.malformed_json_lines}, "
            f"missing_event={diag.missing_event_records}, "
            f"unknown_event={diag.unknown_event_records}"
        )
    return "\n".join(lines)


def budget_result_to_dict(result: BudgetResult) -> dict[str, Any]:
    return {
        "passed": result.passed,
        "total": result.total,
        "completed": result.completed,
        "errors": result.errors,
        "error_rate": result.error_rate,
        "not_ok": result.not_ok,
        "not_ok_rate": result.not_ok_rate,
        "target_error_rates": result.target_error_rates,
        "route_error_rates": result.route_error_rates,
        "reason_rates": result.reason_rates,
        "outcome_rates": result.outcome_rates,
        "upstream_status_rates": result.upstream_status_rates,
        "error_types": result.error_types,
        "reasons": result.reasons,
        "ignored_records": result.ignored_records,
        "parse_diagnostics": {
            "malformed_json": result.parse_diagnostics.malformed_json_lines,
            "missing_event": result.parse_diagnostics.missing_event_records,
            "unknown_event": result.parse_diagnostics.unknown_event_records,
        },
    }


def format_budget_result_json(result: BudgetResult) -> str:
    return json.dumps(
        budget_result_to_dict(result),
        sort_keys=True,
        ensure_ascii=False,
    )


def format_rates(rates: dict[str, float]) -> str:
    if not rates:
        return "none"
    return ", ".join(f"{target}={rate:.4f}" for target, rate in sorted(rates.items()))


def format_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "none"
    return ", ".join(f"{name}={count}" for name, count in sorted(counts.items()))


def parse_reason_rate_budget(raw_budget: str) -> tuple[str, float]:
    if "=" not in raw_budget:
        raise argparse.ArgumentTypeError("expected REASON=RATE")
    reason, raw_rate = raw_budget.split("=", 1)
    if not reason:
        raise argparse.ArgumentTypeError("reason must not be empty")
    try:
        rate = float(raw_rate)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("rate must be a float") from exc
    if rate < 0:
        raise argparse.ArgumentTypeError("rate must be non-negative")
    return reason, rate


def parse_non_negative_rate(raw_rate: str) -> float:
    try:
        rate = float(raw_rate)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("rate must be a float") from exc
    if rate < 0:
        raise argparse.ArgumentTypeError("rate must be non-negative")
    return rate


def parse_upstream_status_rate_budget(raw_budget: str) -> tuple[str, float]:
    if "=" not in raw_budget:
        raise argparse.ArgumentTypeError("expected STATUS=RATE")
    status, raw_rate = raw_budget.split("=", 1)
    if not status.isdigit():
        raise argparse.ArgumentTypeError("status must be an HTTP status code")
    try:
        rate = float(raw_rate)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("rate must be a float") from exc
    if rate < 0:
        raise argparse.ArgumentTypeError("rate must be non-negative")
    return status, rate


def parse_route_error_rate_budget(raw_budget: str) -> tuple[str | None, float]:
    if "=" in raw_budget:
        route, raw_rate = raw_budget.split("=", 1)
        if not route:
            raise argparse.ArgumentTypeError("route_id must not be empty")
        key: str | None = route
    else:
        raw_rate = raw_budget
        key = None
    try:
        rate = float(raw_rate)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("rate must be a float") from exc
    if rate < 0:
        raise argparse.ArgumentTypeError("rate must be non-negative")
    return key, rate


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fail when structured semantic-router logs exceed route_error budgets.",
    )
    parser.add_argument("paths", nargs="*", help="JSONL log files. Reads stdin when omitted.")
    parser.add_argument("--min-total", type=int, default=1)
    parser.add_argument("--max-error-rate", type=float, default=0.0)
    parser.add_argument("--max-target-error-rate", type=float, default=0.0)
    parser.add_argument("--max-not-ok-rate", type=float, default=None)
    parser.add_argument(
        "--max-route-error-rate",
        action="append",
        default=[],
        type=parse_route_error_rate_budget,
        metavar="RATE or ROUTE=RATE",
        help=(
            "Fail when route_id error_rate exceeds a budget. "
            "Provide RATE for a global route budget or ROUTE=RATE for specific route_id budgets. "
            "Repeat to set multiple route-specific budgets."
        ),
    )
    parser.add_argument("--max-malformed-json", type=int, default=None)
    parser.add_argument("--max-missing-event", type=int, default=None)
    parser.add_argument("--max-unknown-event", type=int, default=None)
    parser.add_argument("--max-ignored-records", type=int, default=None)
    parser.add_argument(
        "--max-reason-rate",
        action="append",
        default=[],
        type=parse_reason_rate_budget,
        metavar="REASON=RATE",
        help=(
            "Fail when a route reason exceeds the given rate. "
            "Repeat for multiple reasons, for example embedding_error=0."
        ),
    )
    parser.add_argument(
        "--max-embedding-error-rate",
        type=parse_non_negative_rate,
        default=None,
        help=(
            "Shortcut for --max-reason-rate embedding_error=RATE. "
            "Useful for production patrols because embedding failures silently "
            "fall back to the configured fast route."
        ),
    )
    parser.add_argument(
        "--max-upstream-status-rate",
        action="append",
        default=[],
        type=parse_upstream_status_rate_budget,
        metavar="STATUS=RATE",
        help=(
            "Fail when an upstream_status exceeds the given rate. "
            "Repeat for multiple statuses, for example 400=0."
        ),
    )
    parser.add_argument("--output", choices=("text", "json"), default="text")
    parser.add_argument("--json", action="store_true", help="Shorthand for --output json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    diagnostics = ParseDiagnostics()
    records = list(parse_route_records(iter_lines(args.paths), diagnostics=diagnostics))
    max_route_error_rate: float | dict[str, float] | None = None
    if args.max_route_error_rate:
        default_route_budget = [rate for route, rate in args.max_route_error_rate if route is None]
        specific_route_budgets = {
            route: rate for route, rate in args.max_route_error_rate if route is not None
        }
        if specific_route_budgets:
            max_route_error_rate = specific_route_budgets
        if default_route_budget:
            if isinstance(max_route_error_rate, dict):
                max_route_error_rate["*"] = default_route_budget[-1]
            else:
                max_route_error_rate = default_route_budget[-1]
    max_reason_rates = dict(args.max_reason_rate)
    if args.max_embedding_error_rate is not None:
        max_reason_rates["embedding_error"] = args.max_embedding_error_rate

    result = check_budget(
        records,
        BudgetConfig(
            min_total=args.min_total,
            max_error_rate=args.max_error_rate,
            max_target_error_rate=args.max_target_error_rate,
            max_not_ok_rate=args.max_not_ok_rate,
            max_route_error_rate=max_route_error_rate,
            max_reason_rates=max_reason_rates,
            max_upstream_status_rates=dict(args.max_upstream_status_rate),
            max_malformed_json=args.max_malformed_json,
            max_missing_event=args.max_missing_event,
            max_unknown_event=args.max_unknown_event,
            max_ignored_records=args.max_ignored_records,
        ),
        parse_diagnostics=diagnostics,
    )
    output_mode = "json" if args.json else args.output
    if output_mode == "json":
        print(format_budget_result_json(result))
    else:
        print(format_budget_result(result))
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
