from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import sys
from typing import Any, Iterable

try:
    from scripts.router_log_summary import ParseDiagnostics, parse_route_records
except ModuleNotFoundError:
    from router_log_summary import ParseDiagnostics, parse_route_records


@dataclass(frozen=True)
class BudgetConfig:
    min_total: int = 1
    max_error_rate: float = 0.0
    max_target_error_rate: float = 0.0
    max_reason_rates: dict[str, float] | None = None
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
    target_error_rates: dict[str, float]
    reason_rates: dict[str, float]
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
    reason_totals: Counter[str] = Counter()
    error_types: Counter[str] = Counter()

    for record in records:
        total += 1
        target_model = record.get("target_model")
        if isinstance(target_model, str):
            target_totals[target_model] += 1
        reason = record.get("reason")
        if isinstance(reason, str):
            reason_totals[reason] += 1

        event = record.get("event")
        if event == "route_complete":
            completed += 1
        elif event == "route_error":
            errors += 1
            if isinstance(target_model, str):
                target_errors[target_model] += 1
            error_type = record.get("error_type")
            if isinstance(error_type, str):
                error_types[error_type] += 1

    error_rate = errors / total if total else 0.0
    target_error_rates = {
        target: target_errors[target] / target_total
        for target, target_total in target_totals.items()
    }
    reason_rates = {
        reason: reason_total / total for reason, reason_total in reason_totals.items()
    }

    reasons: list[str] = []
    if total < config.min_total:
        reasons.append(f"total {total} below min_total {config.min_total}")
    if error_rate > config.max_error_rate:
        reasons.append(
            f"error_rate {error_rate:.4f} exceeds max_error_rate {config.max_error_rate:.4f}"
        )
    for target, target_error_rate in sorted(target_error_rates.items()):
        if target_error_rate > config.max_target_error_rate:
            reasons.append(
                f"target {target} error_rate {target_error_rate:.4f} "
                f"exceeds max_target_error_rate {config.max_target_error_rate:.4f}"
            )
    for reason, max_reason_rate in sorted((config.max_reason_rates or {}).items()):
        reason_rate = reason_rates.get(reason, 0.0)
        if reason_rate > max_reason_rate:
            reasons.append(
                f"reason {reason} rate {reason_rate:.4f} "
                f"exceeds max_reason_rate {max_reason_rate:.4f}"
            )
    diagnostics = parse_diagnostics or ParseDiagnostics()
    ignored_records = (
        diagnostics.malformed_json_lines
        + diagnostics.missing_event_records
        + diagnostics.unknown_event_records
    )
    if (
        config.max_malformed_json is not None
        and diagnostics.malformed_json_lines > config.max_malformed_json
    ):
        reasons.append(
            "malformed_json "
            f"{diagnostics.malformed_json_lines} exceeds max_malformed_json "
            f"{config.max_malformed_json}"
        )
    if (
        config.max_missing_event is not None
        and diagnostics.missing_event_records > config.max_missing_event
    ):
        reasons.append(
            "missing_event "
            f"{diagnostics.missing_event_records} exceeds max_missing_event "
            f"{config.max_missing_event}"
        )
    if (
        config.max_unknown_event is not None
        and diagnostics.unknown_event_records > config.max_unknown_event
    ):
        reasons.append(
            "unknown_event "
            f"{diagnostics.unknown_event_records} exceeds max_unknown_event "
            f"{config.max_unknown_event}"
        )
    if (
        config.max_ignored_records is not None
        and ignored_records > config.max_ignored_records
    ):
        reasons.append(
            f"ignored_records {ignored_records} exceeds max_ignored_records "
            f"{config.max_ignored_records}"
        )

    return BudgetResult(
        passed=not reasons,
        total=total,
        completed=completed,
        errors=errors,
        error_rate=error_rate,
        target_error_rates=target_error_rates,
        reason_rates=reason_rates,
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
            f"errors={result.errors} error_rate={result.error_rate:.4f}"
        ),
        f"target_error_rates: {format_rates(result.target_error_rates)}",
        f"reason_rates: {format_rates(result.reason_rates)}",
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fail when structured semantic-router logs exceed route_error budgets.",
    )
    parser.add_argument("--min-total", type=int, default=1)
    parser.add_argument("--max-error-rate", type=float, default=0.0)
    parser.add_argument("--max-target-error-rate", type=float, default=0.0)
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
    parser.add_argument("--max-malformed-json", type=int)
    parser.add_argument("--max-missing-event", type=int)
    parser.add_argument("--max-unknown-event", type=int)
    parser.add_argument("--max-ignored-records", type=int)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    diagnostics = ParseDiagnostics()
    records = list(parse_route_records(sys.stdin, diagnostics=diagnostics))
    result = check_budget(
        records,
        BudgetConfig(
            min_total=args.min_total,
            max_error_rate=args.max_error_rate,
            max_target_error_rate=args.max_target_error_rate,
            max_reason_rates=dict(args.max_reason_rate),
            max_malformed_json=args.max_malformed_json,
            max_missing_event=args.max_missing_event,
            max_unknown_event=args.max_unknown_event,
            max_ignored_records=args.max_ignored_records,
        ),
        parse_diagnostics=diagnostics,
    )
    print(format_budget_result(result))
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
