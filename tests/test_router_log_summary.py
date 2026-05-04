from __future__ import annotations

import json
import subprocess
import sys

from scripts.router_log_summary import (
    ParseDiagnostics,
    format_summary_json,
    format_summary,
    parse_route_records,
    summarize_records,
)


def test_parse_route_records_ignores_access_logs_and_non_route_json():
    logs = "\n".join(
        [
            'INFO:     127.0.0.1:1 - "GET /health HTTP/1.1" 200 OK',
            '{"event":"startup","status":"ok"}',
            '{"event":"route_complete","target_model":"pro-router","stream":true,"duration_ms":1200}',
            '{"event":"route_error","target_model":"pro-router","stream":true,"error_type":"RemoteProtocolError","upstream_status":503,"duration_ms":1400}',
            "not json",
        ]
    )

    records = list(parse_route_records(logs.splitlines()))

    assert records == [
        {
            "event": "route_complete",
            "target_model": "pro-router",
            "stream": True,
            "duration_ms": 1200,
        },
        {
            "event": "route_error",
            "target_model": "pro-router",
            "stream": True,
            "error_type": "RemoteProtocolError",
            "upstream_status": 503,
            "duration_ms": 1400,
        },
    ]


def test_parse_route_records_collects_diagnostics_for_malformed_and_partial_records():
    logs = "\n".join(
        [
            '{"event":"route_complete","target_model":"pro-router"}',
            '{"event":"startup"}',
            '{"target_model":"cheap-router"}',
            '{"event":"route_error",',
        ]
    )
    diagnostics = ParseDiagnostics()

    records = list(parse_route_records(logs.splitlines(), diagnostics=diagnostics))

    assert len(records) == 1
    assert diagnostics.malformed_json_lines == 1
    assert diagnostics.missing_event_records == 1
    assert diagnostics.unknown_event_records == 1


def test_parse_route_records_reports_trailing_malformed_json_after_last_route():
    diagnostics = ParseDiagnostics()

    records = list(
        parse_route_records(
            [
                '{"event":"route_complete","target_model":"pro-router"}',
                '{"event":"route_error",',
            ],
            diagnostics=diagnostics,
        )
    )

    assert len(records) == 1
    assert diagnostics.malformed_json_lines == 1


def test_summarize_records_counts_routes_errors_and_latency():
    records = [
        {
            "event": "route_complete",
            "target_model": "pro-router",
            "reason": "hard_rule:线上",
            "stream": True,
            "duration_ms": 1200,
        },
        {
            "event": "route_complete",
            "target_model": "cheap-router",
            "reason": "embedding_error",
            "stream": False,
            "duration_ms": 300,
        },
        {
            "event": "route_error",
            "target_model": "pro-router",
            "reason": "embedding",
            "stream": True,
            "error_type": "RemoteProtocolError",
            "upstream_status": 503,
            "duration_ms": 1400,
        },
    ]

    summary = summarize_records(records)

    assert summary.total == 3
    assert summary.completed == 2
    assert summary.errors == 1
    assert summary.streams == 2
    assert summary.targets == {"pro-router": 2, "cheap-router": 1}
    assert summary.reasons == {
        "embedding": 1,
        "embedding_error": 1,
        "hard_rule:线上": 1,
    }
    assert summary.error_types == {"RemoteProtocolError": 1}
    assert summary.upstream_statuses == {"503": 1}
    assert summary.max_duration_ms == 1400


def test_format_summary_is_stable_for_runbooks():
    summary = summarize_records(
        [
            {
                "event": "route_error",
                "target_model": "pro-router",
                "reason": "embedding_error",
                "stream": True,
                "error_type": "RemoteProtocolError",
                "upstream_status": 503,
                "duration_ms": 1400,
            }
        ]
    )

    assert format_summary(summary) == "\n".join(
        [
            "total=1 completed=0 errors=1 streams=1 nonstreams=0",
            "targets: pro-router=1",
            "reasons: embedding_error=1",
            "error_types: RemoteProtocolError=1",
            "upstream_statuses: 503=1",
            "max_duration_ms=1400.00",
        ]
    )


def test_format_summary_reports_parse_diagnostics_when_present():
    diagnostics = ParseDiagnostics(
        malformed_json_lines=1,
        missing_event_records=1,
        unknown_event_records=1,
    )
    summary = summarize_records([], parse_diagnostics=diagnostics)

    assert format_summary(summary).endswith(
        "ignored_records: malformed_json=1, missing_event=1, unknown_event=1"
    )


def test_format_summary_json_is_deterministic_and_includes_diagnostics():
    diagnostics = ParseDiagnostics(malformed_json_lines=1, missing_event_records=0, unknown_event_records=1)
    summary = summarize_records(
        [
            {"event": "route_complete", "target_model": "cheap-router", "reason": "embedding", "stream": False},
            {
                "event": "route_error",
                "target_model": "pro-router",
                "reason": "hard_rule",
                "stream": True,
                "error_type": "RemoteProtocolError",
                "upstream_status": 503,
                "duration_ms": 42,
            },
        ],
        parse_diagnostics=diagnostics,
    )

    payload = json.loads(format_summary_json(summary))
    assert payload == {
        "error_types": {"RemoteProtocolError": 1},
        "ignored_records": {"malformed_json": 1, "missing_event": 0, "unknown_event": 1},
        "max_duration_ms": 42.0,
        "nonstreams": 1,
        "reasons": {"embedding": 1, "hard_rule": 1},
        "route_complete": 1,
        "route_error": 1,
        "streams": 1,
        "targets": {"cheap-router": 1, "pro-router": 1},
        "total": 2,
        "upstream_statuses": {"503": 1},
    }


def test_main_json_output_parses_mixed_stream_and_ignores_access_logs():
    logs = "\n".join(
        [
            'INFO:     127.0.0.1:1 - "GET /health HTTP/1.1" 200 OK',
            '{"event":"route_complete","target_model":"cheap-router","reason":"embedding","stream":false}',
            '{"event":"route_error","target_model":"pro-router","reason":"hard_rule","stream":true,"error_type":"UpstreamStatusError","upstream_status":503}',
            '{"event":"startup"}',
            '{"event":"route_error",',
        ]
    )

    completed = subprocess.run(
        [sys.executable, "scripts/router_log_summary.py", "--output", "json"],
        input=logs,
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["total"] == 2
    assert payload["route_complete"] == 1
    assert payload["route_error"] == 1
    assert payload["targets"] == {"cheap-router": 1, "pro-router": 1}
    assert payload["reasons"] == {"embedding": 1, "hard_rule": 1}
    assert payload["upstream_statuses"] == {"503": 1}
    assert payload["ignored_records"] == {
        "malformed_json": 1,
        "missing_event": 0,
        "unknown_event": 1,
    }


def test_main_json_output_matches_checked_in_fixture():
    fixture_path = "tests/samples/router_logs_mixed.log"
    with open(fixture_path, encoding="utf-8") as f:
        logs = f.read()

    completed = subprocess.run(
        [sys.executable, "scripts/router_log_summary.py", "--output", "json"],
        input=logs,
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(completed.stdout)
    assert payload == {
        "error_types": {"UpstreamStatusError": 1},
        "ignored_records": {"malformed_json": 1, "missing_event": 1, "unknown_event": 1},
        "max_duration_ms": 125.0,
        "nonstreams": 1,
        "reasons": {"embedding": 1, "hard_rule": 1},
        "route_complete": 1,
        "route_error": 1,
        "streams": 1,
        "targets": {"cheap-router": 1, "pro-router": 1},
        "total": 2,
        "upstream_statuses": {"503": 1},
    }
