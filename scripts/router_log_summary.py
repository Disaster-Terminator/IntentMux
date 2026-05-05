from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import json
import sys
from typing import Any, Iterable


ROUTE_EVENTS = {"route_complete", "route_error"}


@dataclass
class ParseDiagnostics:
    malformed_json_lines: int = 0
    missing_event_records: int = 0
    unknown_event_records: int = 0


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
    upstream_non_200: dict[str, int]
    max_duration_ms: float
    parse_diagnostics: ParseDiagnostics


def parse_route_records(
    lines: Iterable[str],
    diagnostics: ParseDiagnostics | None = None,
) -> Iterable[dict[str, Any]]:
    for line in lines:
        line = line.strip()
        if not line or "{" not in line:
            continue
        json_start = line.find("{")
        try:
            record = json.loads(line[json_start:])
        except json.JSONDecodeError:
            if diagnostics is not None:
                diagnostics.malformed_json_lines += 1
            continue

        event = record.get("event")
        if event is None:
            if diagnostics is not None:
                diagnostics.missing_event_records += 1
            continue
        if event not in ROUTE_EVENTS:
            if diagnostics is not None:
                diagnostics.unknown_event_records += 1
            continue

        yield record


def summarize_records(
    records: Iterable[dict[str, Any]],
    parse_diagnostics: ParseDiagnostics | None = None,
) -> RouteLogSummary:
    total = 0
    completed = 0
    errors = 0
    streams = 0
    nonstreams = 0
    targets: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    error_types: Counter[str] = Counter()
    upstream_statuses: Counter[str] = Counter()
    upstream_non_200: Counter[str] = Counter()
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
            if upstream_status != 200:
                upstream_non_200[upstream_status_key(record, upstream_status)] += 1

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
        upstream_non_200=dict(upstream_non_200),
        max_duration_ms=max_duration_ms,
        parse_diagnostics=parse_diagnostics or ParseDiagnostics(),
    )


def upstream_status_key(record: dict[str, Any], upstream_status: int) -> str:
    target_model = record.get("target_model")
    if not isinstance(target_model, str):
        target_model = "unknown"
    reason = record.get("reason")
    if not isinstance(reason, str):
        reason = "unknown"
    stream = "true" if record.get("stream") is True else "false"
    return (
        f"status={upstream_status} target={target_model} "
        f"reason={reason} stream={stream}"
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
        f"upstream_non_200: {format_counts(summary.upstream_non_200)}",
        f"max_duration_ms={summary.max_duration_ms:.2f}",
    ]
    diag = summary.parse_diagnostics
    if any(
        (
            diag.malformed_json_lines,
            diag.missing_event_records,
            diag.unknown_event_records,
        )
    ):
        lines.append(
            "ignored_records: "
            f"malformed_json={diag.malformed_json_lines}, "
            f"missing_event={diag.missing_event_records}, "
            f"unknown_event={diag.unknown_event_records}"
        )
    return "\n".join(lines)


def format_summary_json(summary: RouteLogSummary) -> str:
    diag = summary.parse_diagnostics
    payload = {
        "total": summary.total,
        "route_complete": summary.completed,
        "route_error": summary.errors,
        "streams": summary.streams,
        "nonstreams": summary.nonstreams,
        "targets": summary.targets,
        "reasons": summary.reasons,
        "error_types": summary.error_types,
        "upstream_statuses": summary.upstream_statuses,
        "upstream_non_200": summary.upstream_non_200,
        "max_duration_ms": summary.max_duration_ms,
        "ignored_records": {
            "malformed_json": diag.malformed_json_lines,
            "missing_event": diag.missing_event_records,
            "unknown_event": diag.unknown_event_records,
        },
    }
    return json.dumps(payload, sort_keys=True)


def format_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "none"
    return ", ".join(f"{name}={count}" for name, count in sorted(counts.items()))


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize semantic-router route logs.")
    parser.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Shortcut for --output json.",
    )
    args = parser.parse_args()

    diagnostics = ParseDiagnostics()
    records = list(parse_route_records(sys.stdin, diagnostics=diagnostics))
    summary = summarize_records(records, parse_diagnostics=diagnostics)
    output_json = args.json or args.output == "json"
    print(format_summary_json(summary) if output_json else format_summary(summary))


if __name__ == "__main__":
    main()
