from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
import sys
from typing import Any, Iterable


ROUTE_EVENTS = {"route_complete", "route_error"}


@dataclass(frozen=True)
class RouteLogSummary:
    total: int
    completed: int
    errors: int
    streams: int
    nonstreams: int
    targets: dict[str, int]
    reasons: dict[str, int]
    error_types: dict[str, int]
    upstream_statuses: dict[str, int]
    max_duration_ms: float


@dataclass(frozen=True)
class ParseDiagnostics:
    total_lines: int
    parsed_route_events: int
    malformed_json_lines: int
    non_route_json_lines: int
    non_json_lines: int
    missing_target_model: int
    missing_stream_flag: int


def parse_route_records(lines: Iterable[str]) -> Iterable[dict[str, Any]]:
    for line in lines:
        line = line.strip()
        if not line or "{" not in line:
            continue
        json_start = line.find("{")
        try:
            record = json.loads(line[json_start:])
        except json.JSONDecodeError:
            continue
        if record.get("event") in ROUTE_EVENTS:
            yield record


def parse_route_records_with_diagnostics(
    lines: Iterable[str],
) -> tuple[list[dict[str, Any]], ParseDiagnostics]:
    records: list[dict[str, Any]] = []
    total_lines = 0
    malformed_json_lines = 0
    non_route_json_lines = 0
    non_json_lines = 0
    missing_target_model = 0
    missing_stream_flag = 0

    for raw_line in lines:
        total_lines += 1
        line = raw_line.strip()
        if not line or "{" not in line:
            non_json_lines += 1
            continue
        json_start = line.find("{")
        try:
            record = json.loads(line[json_start:])
        except json.JSONDecodeError:
            malformed_json_lines += 1
            continue
        if record.get("event") not in ROUTE_EVENTS:
            non_route_json_lines += 1
            continue
        if not isinstance(record.get("target_model"), str):
            missing_target_model += 1
        if not isinstance(record.get("stream"), bool):
            missing_stream_flag += 1
        records.append(record)

    return records, ParseDiagnostics(
        total_lines=total_lines,
        parsed_route_events=len(records),
        malformed_json_lines=malformed_json_lines,
        non_route_json_lines=non_route_json_lines,
        non_json_lines=non_json_lines,
        missing_target_model=missing_target_model,
        missing_stream_flag=missing_stream_flag,
    )


def summarize_records(records: Iterable[dict[str, Any]]) -> RouteLogSummary:
    total = 0
    completed = 0
    errors = 0
    streams = 0
    nonstreams = 0
    targets: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    error_types: Counter[str] = Counter()
    upstream_statuses: Counter[str] = Counter()
    max_duration_ms = 0.0

    for record in records:
        total += 1
        event = record.get("event")
        if event == "route_complete":
            completed += 1
        elif event == "route_error":
            errors += 1
            error_type = record.get("error_type")
            if isinstance(error_type, str):
                error_types[error_type] += 1

        if record.get("stream") is True:
            streams += 1
        else:
            nonstreams += 1

        target_model = record.get("target_model")
        if isinstance(target_model, str):
            targets[target_model] += 1

        reason = record.get("reason")
        if isinstance(reason, str):
            reasons[reason] += 1

        duration_ms = record.get("duration_ms")
        if isinstance(duration_ms, int | float):
            max_duration_ms = max(max_duration_ms, float(duration_ms))

        upstream_status = record.get("upstream_status")
        if isinstance(upstream_status, int):
            upstream_statuses[str(upstream_status)] += 1

    return RouteLogSummary(
        total=total,
        completed=completed,
        errors=errors,
        streams=streams,
        nonstreams=nonstreams,
        targets=dict(targets),
        reasons=dict(reasons),
        error_types=dict(error_types),
        upstream_statuses=dict(upstream_statuses),
        max_duration_ms=max_duration_ms,
    )


def format_summary(summary: RouteLogSummary) -> str:
    lines = [
        (
            f"total={summary.total} completed={summary.completed} "
            f"errors={summary.errors} streams={summary.streams} "
            f"nonstreams={summary.nonstreams}"
        ),
        f"targets: {format_counts(summary.targets)}",
        f"reasons: {format_counts(summary.reasons)}",
        f"error_types: {format_counts(summary.error_types)}",
        f"upstream_statuses: {format_counts(summary.upstream_statuses)}",
        f"max_duration_ms={summary.max_duration_ms:.2f}",
    ]
    return "\n".join(lines)


def format_diagnostics(diagnostics: ParseDiagnostics) -> str:
    return (
        "parse_diagnostics: "
        f"total_lines={diagnostics.total_lines} "
        f"parsed_route_events={diagnostics.parsed_route_events} "
        f"malformed_json_lines={diagnostics.malformed_json_lines} "
        f"non_route_json_lines={diagnostics.non_route_json_lines} "
        f"non_json_lines={diagnostics.non_json_lines} "
        f"missing_target_model={diagnostics.missing_target_model} "
        f"missing_stream_flag={diagnostics.missing_stream_flag}"
    )


def format_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "none"
    return ", ".join(f"{name}={count}" for name, count in sorted(counts.items()))


def main() -> None:
    records, diagnostics = parse_route_records_with_diagnostics(sys.stdin)
    summary = summarize_records(records)
    print(format_summary(summary))
    print(format_diagnostics(diagnostics))


if __name__ == "__main__":
    main()
