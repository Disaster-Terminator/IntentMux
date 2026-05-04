from __future__ import annotations

from scripts.router_log_summary import (
    format_diagnostics,
    format_summary,
    parse_route_records,
    parse_route_records_with_diagnostics,
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


def test_parse_route_records_with_diagnostics_reports_malformed_and_partial_lines():
    records, diagnostics = parse_route_records_with_diagnostics(
        [
            'INFO:     127.0.0.1:1 - "GET /health HTTP/1.1" 200 OK',
            '{"event":"startup","status":"ok"}',
            '{"event":"route_complete","reason":"hard_rule:线上","stream":true}',
            '{"event":"route_error","target_model":"pro-router"}',
            '{"event":"route_complete","target_model":"cheap-router","stream":false}',
            "{broken",
        ]
    )

    assert len(records) == 3
    assert diagnostics.total_lines == 6
    assert diagnostics.parsed_route_events == 3
    assert diagnostics.malformed_json_lines == 1
    assert diagnostics.non_route_json_lines == 1
    assert diagnostics.non_json_lines == 1
    assert diagnostics.missing_target_model == 1
    assert diagnostics.missing_stream_flag == 1
    assert (
        format_diagnostics(diagnostics)
        == "parse_diagnostics: total_lines=6 parsed_route_events=3 "
        "malformed_json_lines=1 non_route_json_lines=1 non_json_lines=1 "
        "missing_target_model=1 missing_stream_flag=1"
    )
