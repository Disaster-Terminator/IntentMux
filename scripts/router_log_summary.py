from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import sys
from typing import Any, Iterable


ROUTE_EVENTS = {"route_complete", "route_error"}


@dataclass
class ParseDiagnostics:
    malformed_json_lines: int = 0
    missing_event_records: int = 0
    unknown_event_records: int = 0


@dataclass(frozen=True)
class SlowRequest:
    duration_ms: float
    timestamp: str | None
    request_id: str | None
    route_id: str | None
    target_model: str | None
    reason: str | None
    upstream_status: int | None
    decision_ms: float | None
    upstream_ms: float | None
    upstream_headers_ms: float | None
    upstream_body_ms: float | None


@dataclass(frozen=True)
class RouteLogSummary:
    total: int
    completed: int
    errors: int
    streams: int
    nonstreams: int
    routes: dict[str, int]
    targets: dict[str, int]
    reasons: dict[str, int]
    error_types: dict[str, int]
    outcomes: dict[str, int]
    not_ok: int
    upstream_statuses: dict[str, int]
    upstream_non_200: dict[str, int]
    max_duration_ms: float
    duration_percentiles_ms: dict[str, float]
    slow_requests: list[SlowRequest]
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
    slow_request_limit: int = 5,
) -> RouteLogSummary:
    total = 0
    completed = 0
    errors = 0
    streams = 0
    nonstreams = 0
    routes: Counter[str] = Counter()
    targets: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    error_types: Counter[str] = Counter()
    outcomes: Counter[str] = Counter()
    not_ok = 0
    upstream_statuses: Counter[str] = Counter()
    upstream_non_200: Counter[str] = Counter()
    max_duration_ms = 0.0
    duration_samples: list[float] = []
    slow_requests: list[SlowRequest] = []

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

        route_id = record.get("route_id")
        if isinstance(route_id, str):
            routes[route_id] += 1

        target_model = record.get("target_model")
        if isinstance(target_model, str):
            targets[target_model] += 1

        reason = record.get("reason")
        if isinstance(reason, str):
            reasons[reason] += 1

        outcome = outcome_from_record(record)
        outcomes[outcome] += 1
        if not ok_from_record(record):
            not_ok += 1

        duration_ms = record.get("duration_ms")
        if isinstance(duration_ms, int | float):
            duration_ms_float = float(duration_ms)
            max_duration_ms = max(max_duration_ms, duration_ms_float)
            duration_samples.append(duration_ms_float)
            slow_requests.append(slow_request_from_record(record, duration_ms_float))

        upstream_status = record.get("upstream_status")
        if isinstance(upstream_status, int):
            upstream_statuses[str(upstream_status)] += 1
            if not 200 <= upstream_status <= 299:
                upstream_non_200[upstream_status_key(record, upstream_status)] += 1

    return RouteLogSummary(
        total=total,
        completed=completed,
        errors=errors,
        streams=streams,
        nonstreams=nonstreams,
        routes=dict(routes),
        targets=dict(targets),
        reasons=dict(reasons),
        error_types=dict(error_types),
        outcomes=dict(outcomes),
        not_ok=not_ok,
        upstream_statuses=dict(upstream_statuses),
        upstream_non_200=dict(upstream_non_200),
        max_duration_ms=max_duration_ms,
        duration_percentiles_ms=duration_percentiles(duration_samples),
        slow_requests=sorted(
            slow_requests,
            key=lambda sample: sample.duration_ms,
            reverse=True,
        )[: max(0, slow_request_limit)],
        parse_diagnostics=parse_diagnostics or ParseDiagnostics(),
    )


def duration_percentiles(samples: list[float]) -> dict[str, float]:
    if not samples:
        return {}
    sorted_samples = sorted(samples)
    return {
        "p50": upper_percentile(sorted_samples, 0.50),
        "p90": upper_percentile(sorted_samples, 0.90),
        "p95": upper_percentile(sorted_samples, 0.95),
        "p99": upper_percentile(sorted_samples, 0.99),
    }


def upper_percentile(sorted_samples: list[float], quantile: float) -> float:
    if len(sorted_samples) == 1:
        return sorted_samples[0]
    index = math.ceil((len(sorted_samples) - 1) * quantile)
    return sorted_samples[index]


def slow_request_from_record(record: dict[str, Any], duration_ms: float) -> SlowRequest:
    timestamp = string_or_none(record.get("timestamp"))
    if timestamp is None:
        timestamp = string_or_none(record.get("ts"))
    upstream_status = record.get("upstream_status")
    return SlowRequest(
        duration_ms=duration_ms,
        timestamp=timestamp,
        request_id=string_or_none(record.get("request_id")),
        route_id=string_or_none(record.get("route_id")),
        target_model=string_or_none(record.get("target_model")),
        reason=string_or_none(record.get("reason")),
        upstream_status=upstream_status if isinstance(upstream_status, int) else None,
        decision_ms=number_or_none(record.get("decision_ms")),
        upstream_ms=number_or_none(record.get("upstream_ms")),
        upstream_headers_ms=number_or_none(record.get("upstream_headers_ms")),
        upstream_body_ms=number_or_none(record.get("upstream_body_ms")),
    )


def string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def number_or_none(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) else None


def ok_from_record(record: dict[str, Any]) -> bool:
    ok = record.get("ok")
    if isinstance(ok, bool):
        return ok
    if record.get("event") == "route_error":
        return False
    upstream_status = record.get("upstream_status")
    if isinstance(upstream_status, int):
        return 200 <= upstream_status <= 299
    return True


def outcome_from_record(record: dict[str, Any]) -> str:
    outcome = record.get("outcome")
    if isinstance(outcome, str):
        return outcome
    upstream_status = record.get("upstream_status")
    if isinstance(upstream_status, int) and not 200 <= upstream_status <= 299:
        return "upstream_non_200"
    if record.get("event") == "route_error":
        return "route_error"
    return "success"


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
        f"routes: {format_counts(summary.routes)}",
        f"targets: {format_counts(summary.targets)}",
        f"reasons: {format_counts(summary.reasons)}",
        f"error_types: {format_counts(summary.error_types)}",
        f"outcomes: {format_counts(summary.outcomes)}",
        f"not_ok={summary.not_ok}",
        f"upstream_statuses: {format_counts(summary.upstream_statuses)}",
        f"upstream_non_200: {format_counts(summary.upstream_non_200)}",
        f"max_duration_ms={summary.max_duration_ms:.2f}",
        f"duration_percentiles_ms: {format_float_counts(summary.duration_percentiles_ms)}",
    ]
    if summary.slow_requests:
        lines.append("slow_requests:")
        lines.extend(format_slow_request(sample) for sample in summary.slow_requests)
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
        "routes": summary.routes,
        "targets": summary.targets,
        "reasons": summary.reasons,
        "error_types": summary.error_types,
        "outcomes": summary.outcomes,
        "not_ok": summary.not_ok,
        "upstream_statuses": summary.upstream_statuses,
        "upstream_non_200": summary.upstream_non_200,
        "max_duration_ms": summary.max_duration_ms,
        "duration_percentiles_ms": summary.duration_percentiles_ms,
        "slow_requests": [asdict(sample) for sample in summary.slow_requests],
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


def format_float_counts(counts: dict[str, float]) -> str:
    if not counts:
        return "none"
    return ", ".join(f"{name}={value:.2f}" for name, value in counts.items())


def format_slow_request(sample: SlowRequest) -> str:
    line = (
        f"- duration_ms={sample.duration_ms:.2f} "
        f"timestamp={sample.timestamp or 'unknown'} "
        f"request_id={sample.request_id or 'unknown'} "
        f"route={sample.route_id or 'unknown'} "
        f"target={sample.target_model or 'unknown'} "
        f"reason={sample.reason or 'unknown'} "
        f"upstream_status={sample.upstream_status if sample.upstream_status is not None else 'unknown'}"
    )
    timing_fields = {
        "decision_ms": sample.decision_ms,
        "upstream_ms": sample.upstream_ms,
        "upstream_headers_ms": sample.upstream_headers_ms,
        "upstream_body_ms": sample.upstream_body_ms,
    }
    for name, value in timing_fields.items():
        if value is not None:
            line += f" {name}={value:.2f}"
    return line


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize IntentMux route logs.")
    parser.add_argument("paths", nargs="*", help="JSONL log files. Reads stdin when omitted.")
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
    parser.add_argument(
        "--slow-request-limit",
        type=int,
        default=5,
        help="Number of slowest requests to print/include (default: 5). Use 0 to disable.",
    )
    args = parser.parse_args()

    diagnostics = ParseDiagnostics()
    records = parse_route_records(iter_lines(args.paths), diagnostics=diagnostics)
    summary = summarize_records(
        records,
        parse_diagnostics=diagnostics,
        slow_request_limit=args.slow_request_limit,
    )
    output_json = args.json or args.output == "json"
    print(format_summary_json(summary) if output_json else format_summary(summary))


def iter_lines(paths: list[str]) -> Iterable[str]:
    if not paths:
        yield from sys.stdin
        return
    for raw_path in paths:
        with Path(raw_path).open("r", encoding="utf-8") as file:
            yield from file


if __name__ == "__main__":
    main()
