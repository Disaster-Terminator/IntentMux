from __future__ import annotations

import json
import subprocess
import sys

from scripts.router_log_summary import (
    ParseDiagnostics,
    format_summary,
    format_summary_json,
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


def test_format_summary_json_mixed_records_is_deterministic():
    logs = "\n".join(
        [
            'INFO:     127.0.0.1:1 - "GET /health HTTP/1.1" 200 OK',
            '{"event":"route_complete","target_model":"pro-router","reason":"hard_rule","stream":true,"duration_ms":1200}',
            '{"event":"route_error","target_model":"cheap-router","reason":"embedding_error","stream":false,"error_type":"RemoteProtocolError","upstream_status":503,"duration_ms":800}',
            '{"event":"route_error",',
        ]
    )
    diagnostics = ParseDiagnostics()
    records = list(parse_route_records(logs.splitlines(), diagnostics=diagnostics))
    summary = summarize_records(records, parse_diagnostics=diagnostics)

    payload = json.loads(format_summary_json(summary))

    assert payload == {
        "error_types": {"RemoteProtocolError": 1},
        "ignored_records": {
            "malformed_json": 1,
            "missing_event": 0,
            "unknown_event": 0,
        },
        "max_duration_ms": 1200.0,
        "nonstreams": 1,
        "reasons": {"embedding_error": 1, "hard_rule": 1},
        "route_complete": 1,
        "route_error": 1,
        "streams": 1,
        "targets": {"cheap-router": 1, "pro-router": 1},
        "total": 2,
        "upstream_statuses": {"503": 1},
    }


def test_main_json_output_flag_outputs_json_summary(tmp_path):
    logs = "\n".join(
        [
            '{"event":"route_complete","target_model":"pro-router","reason":"hard_rule","stream":true,"duration_ms":100}',
            '{"event":"route_error","target_model":"pro-router","reason":"embedding","stream":true,"error_type":"RemoteProtocolError","upstream_status":504,"duration_ms":200}',
            "not json",
        ]
    )

    result = subprocess.run(
        [sys.executable, "scripts/router_log_summary.py", "--json"],
        input=logs,
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["route_complete"] == 1
    assert payload["route_error"] == 1
    assert payload["ignored_records"] == {
        "malformed_json": 0,
        "missing_event": 0,
        "unknown_event": 0,
    }
