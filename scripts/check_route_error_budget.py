from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import sys
from typing import Any, Iterable

try:
    from scripts.router_log_summary import parse_route_records
except ModuleNotFoundError:
    from router_log_summary import parse_route_records


@dataclass(frozen=True)
class BudgetConfig:
    min_total: int = 1
    max_error_rate: float = 0.0
    max_target_error_rate: float = 0.0


@dataclass(frozen=True)
class BudgetResult:
    passed: bool
    total: int
    completed: int
    errors: int
    error_rate: float
    target_error_rates: dict[str, float]
    error_types: dict[str, int]
    reasons: list[str]


def check_budget(records: Iterable[dict[str, Any]], config: BudgetConfig) -> BudgetResult:
    total = 0
    completed = 0
    errors = 0
    target_totals: Counter[str] = Counter()
    target_errors: Counter[str] = Counter()
    error_types: Counter[str] = Counter()

    for record in records:
        total += 1
        target_model = record.get("target_model")
        if isinstance(target_model, str):
            target_totals[target_model] += 1

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

    return BudgetResult(
        passed=not reasons,
        total=total,
        completed=completed,
        errors=errors,
        error_rate=error_rate,
        target_error_rates=target_error_rates,
        error_types=dict(error_types),
        reasons=reasons,
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
        f"error_types: {format_counts(result.error_types)}",
    ]
    if result.reasons:
        lines.append(f"reasons: {'; '.join(result.reasons)}")
    return "\n".join(lines)


def format_rates(rates: dict[str, float]) -> str:
    if not rates:
        return "none"
    return ", ".join(f"{target}={rate:.4f}" for target, rate in sorted(rates.items()))


def format_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "none"
    return ", ".join(f"{name}={count}" for name, count in sorted(counts.items()))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fail when structured semantic-router logs exceed route_error budgets.",
    )
    parser.add_argument("--min-total", type=int, default=1)
    parser.add_argument("--max-error-rate", type=float, default=0.0)
    parser.add_argument("--max-target-error-rate", type=float, default=0.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = check_budget(
        parse_route_records(sys.stdin),
        BudgetConfig(
            min_total=args.min_total,
            max_error_rate=args.max_error_rate,
            max_target_error_rate=args.max_target_error_rate,
        ),
    )
    print(format_budget_result(result))
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
