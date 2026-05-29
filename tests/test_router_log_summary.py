from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.router_log_summary import (
    ParseDiagnostics,
    filter_records_by_window,
    format_summary,
    format_summary_json,
    iter_lines,
    parse_route_records,
    summarize_records,
)


def test_access_log_only_lines_are_silently_ignored():
    logs = """
INFO:     127.0.0.1:53210 - \"GET /health HTTP/1.1\" 200 OK
INFO:     127.0.0.1:53210 - \"POST /v1/chat/completions HTTP/1.1\" 200 OK
INFO:     127.0.0.1:53210 - \"GET /metrics HTTP/1.1\" 404 Not Found
""".strip()
    diagnostics = ParseDiagnostics()

    records = list(parse_route_records(logs.splitlines(), diagnostics=diagnostics))

    assert records == []
    assert diagnostics == ParseDiagnostics()


def test_iter_lines_streams_files_without_preloading(monkeypatch, tmp_path: Path):
    log_path = tmp_path / "routes.jsonl"
    log_path.write_text("first\nsecond\n", encoding="utf-8")
    opened: list[str] = []
    real_open = Path.open

    def tracking_open(self: Path, *args, **kwargs):
        opened.append(str(self))
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", tracking_open)
    lines = iter_lines([str(log_path)])

    assert opened == []
    assert next(lines) == "first\n"
    assert opened == [str(log_path)]
    assert list(lines) == ["second\n"]


def test_parse_route_records_ignores_access_logs_and_non_route_json():
    logs = "\n".join(
        [
            'INFO:     127.0.0.1:1 - "GET /health HTTP/1.1" 200 OK',
            '{"event":"startup","status":"ok"}',
            '{"event":"route_complete","route_id":"deep","target_model":"deep-upstream","stream":true,"duration_ms":1200}',
            '{"event":"route_error","target_model":"deep-upstream","stream":true,"error_type":"RemoteProtocolError","upstream_status":503,"duration_ms":1400}',
            "not json",
        ]
    )

    records = list(parse_route_records(logs.splitlines()))

    assert records == [
        {
            "event": "route_complete",
            "route_id": "deep",
            "target_model": "deep-upstream",
            "stream": True,
            "duration_ms": 1200,
        },
        {
            "event": "route_error",
            "target_model": "deep-upstream",
            "stream": True,
            "error_type": "RemoteProtocolError",
            "upstream_status": 503,
            "duration_ms": 1400,
        },
    ]


def test_parse_route_records_collects_diagnostics_for_malformed_and_partial_records():
    logs = "\n".join(
        [
            '{"event":"route_complete","target_model":"deep-upstream"}',
            '{"event":"startup"}',
            '{"target_model":"lite-upstream"}',
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
                '{"event":"route_complete","target_model":"deep-upstream"}',
                '{"event":"route_error",',
            ],
            diagnostics=diagnostics,
        )
    )

    assert len(records) == 1
    assert diagnostics.malformed_json_lines == 1


def test_filter_records_by_window_uses_latest_record_timestamp_as_anchor():
    records = [
        {
            "event": "route_complete",
            "request_id": "old",
            "ts": "2026-05-29T10:00:00Z",
        },
        {
            "event": "route_complete",
            "request_id": "recent",
            "timestamp": "2026-05-29T10:09:00+00:00",
        },
        {
            "event": "route_complete",
            "request_id": "latest",
            "ts": "2026-05-29T10:10:00Z",
        },
        {
            "event": "route_complete",
            "request_id": "missing-ts",
        },
    ]

    filtered = filter_records_by_window(records, window_minutes=2)

    assert [record["request_id"] for record in filtered] == ["recent", "latest"]


def test_summarize_records_counts_routes_errors_and_latency():
    records = [
        {
            "event": "route_complete",
            "route_id": "deep",
            "target_model": "deep-upstream",
            "reason": "hard_rule:线上",
            "stream": True,
            "duration_ms": 1200,
        },
        {
            "event": "route_complete",
            "route_id": "lite",
            "target_model": "lite-upstream",
            "reason": "embedding_error",
            "stream": False,
            "duration_ms": 300,
        },
        {
            "event": "route_error",
            "route_id": "deep",
            "target_model": "deep-upstream",
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
    assert summary.nonstreams == 1
    assert summary.targets == {"deep-upstream": 2, "lite-upstream": 1}
    assert summary.routes == {"deep": 2, "lite": 1}
    assert summary.reasons == {
        "embedding": 1,
        "embedding_error": 1,
        "hard_rule:线上": 1,
    }
    assert summary.error_types == {"RemoteProtocolError": 1}
    assert summary.upstream_statuses == {"503": 1}
    assert summary.outcomes == {"success": 2, "upstream_non_200": 1}
    assert summary.not_ok == 1
    assert summary.upstream_non_200 == {
        "status=503 target=deep-upstream reason=embedding stream=true": 1
    }
    assert summary.max_duration_ms == 1400
    assert summary.duration_percentiles_ms == {
        "p50": 1200.0,
        "p90": 1400.0,
        "p95": 1400.0,
        "p99": 1400.0,
    }
    assert [sample.duration_ms for sample in summary.slow_requests] == [
        1400.0,
        1200.0,
        300.0,
    ]


def test_summarize_records_limits_slow_request_samples_and_preserves_context():
    records = [
        {
            "event": "route_complete",
            "timestamp": "2026-05-12T00:00:00Z",
            "request_id": "req-lite",
            "route_id": "lite",
            "target_model": "lite-upstream",
            "reason": "low_confidence",
            "stream": True,
            "upstream_status": 200,
            "duration_ms": 100,
            "decision_ms": 1.5,
            "upstream_ms": 98.5,
        },
        {
            "event": "route_complete",
            "ts": "2026-05-12T00:00:01Z",
            "request_id": "req-slow",
            "route_id": "deep",
            "target_model": "deep-upstream",
            "reason": "hard_rule:安全",
            "stream": True,
            "upstream_status": 400,
            "duration_ms": 2500,
            "decision_ms": 2.5,
            "upstream_ms": 2490.5,
            "upstream_headers_ms": 50.0,
            "upstream_body_ms": 2440.5,
        },
        {
            "event": "route_complete",
            "timestamp": "2026-05-12T00:00:02Z",
            "request_id": "req-mid",
            "route_id": "lite",
            "target_model": "lite-upstream",
            "reason": "embedding_error",
            "stream": False,
            "upstream_status": 200,
            "duration_ms": 1200,
        },
    ]

    summary = summarize_records(records, slow_request_limit=2)

    assert summary.duration_percentiles_ms == {
        "p50": 1200.0,
        "p90": 2500.0,
        "p95": 2500.0,
        "p99": 2500.0,
    }
    assert [
        (
            sample.timestamp,
            sample.request_id,
            sample.duration_ms,
            sample.route_id,
            sample.target_model,
            sample.reason,
            sample.upstream_status,
            sample.decision_ms,
            sample.upstream_ms,
            sample.upstream_headers_ms,
            sample.upstream_body_ms,
        )
        for sample in summary.slow_requests
    ] == [
        (
            "2026-05-12T00:00:01Z",
            "req-slow",
            2500.0,
            "deep",
            "deep-upstream",
            "hard_rule:安全",
            400,
            2.5,
            2490.5,
            50.0,
            2440.5,
        ),
        (
            "2026-05-12T00:00:02Z",
            "req-mid",
            1200.0,
            "lite",
            "lite-upstream",
            "embedding_error",
            200,
            None,
            None,
            None,
            None,
        ),
    ]


def test_summarize_records_counts_config_and_route_bank_versions():
    summary = summarize_records(
        [
            {
                "event": "route_complete",
                "config_source": "ROUTER_CONFIG",
                "config_sha256": "a" * 64,
                "route_bank_sha256": "b" * 64,
            },
            {
                "event": "route_complete",
                "config_source": "ROUTER_CONFIG",
                "config_sha256": "a" * 64,
                "route_bank_sha256": "c" * 64,
            },
        ]
    )

    assert summary.config_sources == {"ROUTER_CONFIG": 2}
    assert summary.config_sha256s == {"a" * 64: 2}
    assert summary.route_bank_sha256s == {"b" * 64: 1, "c" * 64: 1}


def test_summarize_records_totals_safe_token_usage():
    summary = summarize_records(
        [
            {
                "event": "route_complete",
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
            {
                "event": "route_complete",
                "prompt_tokens": 3,
                "completion_tokens": 7,
                "total_tokens": 10,
            },
        ]
    )

    assert summary.token_totals == {
        "prompt_tokens": 13,
        "completion_tokens": 12,
        "total_tokens": 25,
    }


def test_format_summary_is_stable_for_runbooks():
    summary = summarize_records(
        [
            {
                "event": "route_error",
                "route_id": "deep",
                "target_model": "deep-upstream",
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
            "routes: deep=1",
            "targets: deep-upstream=1",
            "reasons: embedding_error=1",
            "error_types: RemoteProtocolError=1",
            "outcomes: upstream_non_200=1",
            "not_ok=1",
            "upstream_statuses: 503=1",
            "upstream_non_200: status=503 target=deep-upstream reason=embedding_error stream=true=1",
            "config_sources: none",
            "config_sha256s: none",
            "route_bank_sha256s: none",
            "token_totals: none",
            "max_duration_ms=1400.00",
            "duration_percentiles_ms: p50=1400.00, p90=1400.00, p95=1400.00, p99=1400.00",
            "slow_requests:",
            "- duration_ms=1400.00 timestamp=unknown request_id=unknown route=deep target=deep-upstream reason=embedding_error upstream_status=503",
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
    diagnostics = ParseDiagnostics(
        malformed_json_lines=1, missing_event_records=0, unknown_event_records=1
    )
    summary = summarize_records(
        [
            {
                "event": "route_complete",
                "target_model": "lite-upstream",
                "reason": "embedding",
                "stream": False,
            },
            {
                "event": "route_error",
                "target_model": "deep-upstream",
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
        "config_sources": {},
        "config_sha256s": {},
        "route_bank_sha256s": {},
        "token_totals": {},
        "ignored_records": {
            "malformed_json": 1,
            "missing_event": 0,
            "unknown_event": 1,
        },
        "max_duration_ms": 42.0,
        "duration_percentiles_ms": {
            "p50": 42.0,
            "p90": 42.0,
            "p95": 42.0,
            "p99": 42.0,
        },
        "nonstreams": 1,
        "not_ok": 1,
        "outcomes": {"success": 1, "upstream_non_200": 1},
        "reasons": {"embedding": 1, "hard_rule": 1},
        "route_complete": 1,
        "route_error": 1,
        "routes": {},
        "streams": 1,
        "targets": {"lite-upstream": 1, "deep-upstream": 1},
        "total": 2,
        "upstream_non_200": {
            "status=503 target=deep-upstream reason=hard_rule stream=true": 1
        },
        "upstream_statuses": {"503": 1},
        "slow_requests": [
            {
                "duration_ms": 42.0,
                "decision_ms": None,
                "reason": "hard_rule",
                "request_id": None,
                "route_id": None,
                "target_model": "deep-upstream",
                "timestamp": None,
                "upstream_body_ms": None,
                "upstream_headers_ms": None,
                "upstream_ms": None,
                "upstream_status": 503,
            }
        ],
    }


def test_main_json_output_parses_mixed_stream_and_ignores_access_logs():
    logs = "\n".join(
        [
            'INFO:     127.0.0.1:1 - "GET /health HTTP/1.1" 200 OK',
            '{"event":"route_complete","target_model":"lite-upstream","reason":"embedding","stream":false}',
            '{"event":"route_error","target_model":"deep-upstream","reason":"hard_rule","stream":true,"error_type":"UpstreamStatusError","upstream_status":503}',
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
    assert payload["targets"] == {"lite-upstream": 1, "deep-upstream": 1}
    assert payload["reasons"] == {"embedding": 1, "hard_rule": 1}
    assert payload["upstream_statuses"] == {"503": 1}
    assert payload["outcomes"] == {"success": 1, "upstream_non_200": 1}
    assert payload["not_ok"] == 1
    assert payload["upstream_non_200"] == {
        "status=503 target=deep-upstream reason=hard_rule stream=true": 1
    }
    assert payload["ignored_records"] == {
        "malformed_json": 1,
        "missing_event": 0,
        "unknown_event": 1,
    }


def test_main_short_json_flag_outputs_machine_readable_json():
    logs = """
INFO:     127.0.0.1:53000 - \"POST /v1/chat/completions HTTP/1.1\" 200 OK
2026-05-04T12:00:00.000Z INFO router {"event":"route_complete","target_model":"safe-model","reason":"hard_rule","stream":false,"upstream_status":200,"duration_ms":12.5}
2026-05-04T12:00:00.100Z INFO router {"event":"route_error","target_model":"fallback-model","reason":"embedding_error","stream":true,"error_type":"RemoteProtocolError","upstream_status":503,"duration_ms":40}
2026-05-04T12:00:00.200Z INFO router {"model":"missing-event"}
2026-05-04T12:00:00.300Z INFO router {"event":"startup"}
2026-05-04T12:00:00.400Z INFO router {"event":"route_error",
""".strip()

    completed = subprocess.run(
        [sys.executable, "scripts/router_log_summary.py", "--json"],
        input=logs,
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(completed.stdout)
    assert payload == {
        "error_types": {"RemoteProtocolError": 1},
        "config_sources": {},
        "config_sha256s": {},
        "route_bank_sha256s": {},
        "token_totals": {},
        "ignored_records": {
            "malformed_json": 1,
            "missing_event": 1,
            "unknown_event": 1,
        },
        "max_duration_ms": 40.0,
        "duration_percentiles_ms": {
            "p50": 40.0,
            "p90": 40.0,
            "p95": 40.0,
            "p99": 40.0,
        },
        "nonstreams": 1,
        "not_ok": 1,
        "outcomes": {"success": 1, "upstream_non_200": 1},
        "reasons": {"embedding_error": 1, "hard_rule": 1},
        "route_complete": 1,
        "route_error": 1,
        "routes": {},
        "streams": 1,
        "targets": {"fallback-model": 1, "safe-model": 1},
        "total": 2,
        "upstream_non_200": {
            "status=503 target=fallback-model reason=embedding_error stream=true": 1
        },
        "upstream_statuses": {"200": 1, "503": 1},
        "slow_requests": [
            {
                "duration_ms": 40.0,
                "decision_ms": None,
                "reason": "embedding_error",
                "request_id": None,
                "route_id": None,
                "target_model": "fallback-model",
                "timestamp": None,
                "upstream_body_ms": None,
                "upstream_headers_ms": None,
                "upstream_ms": None,
                "upstream_status": 503,
            },
            {
                "duration_ms": 12.5,
                "decision_ms": None,
                "reason": "hard_rule",
                "request_id": None,
                "route_id": None,
                "target_model": "safe-model",
                "timestamp": None,
                "upstream_body_ms": None,
                "upstream_headers_ms": None,
                "upstream_ms": None,
                "upstream_status": 200,
            },
        ],
    }


def test_contract_fixture_summary_separates_routes_and_targets():
    fixture = Path("tests/samples/router_logs_contract.ndjson")
    diagnostics = ParseDiagnostics()
    records = list(
        parse_route_records(fixture.read_text().splitlines(), diagnostics=diagnostics)
    )

    summary = summarize_records(records, parse_diagnostics=diagnostics)

    assert summary.total == 4
    assert summary.completed == 2
    assert summary.errors == 2
    assert summary.routes == {"chat.deep": 2}
    assert summary.targets == {
        "base-router": 1,
        "legacy-router": 1,
        "your-deep-model": 2,
    }
    assert summary.error_types == {"RemoteProtocolError": 1, "UpstreamStatusError": 1}
    assert summary.parse_diagnostics.malformed_json_lines == 1
    assert summary.parse_diagnostics.unknown_event_records == 1


def test_main_accepts_log_file_paths(tmp_path: Path):
    log_path = tmp_path / "routes.jsonl"
    log_path.write_text(
        "\n".join(
            [
                '{"event":"route_complete","target_model":"lite-upstream","ok":true,"outcome":"success","upstream_status":200}',
                '{"event":"route_complete","target_model":"lite-upstream","ok":false,"outcome":"upstream_non_200","upstream_status":400}',
            ]
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, "scripts/router_log_summary.py", str(log_path), "--json"],
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["total"] == 2
    assert payload["not_ok"] == 1
    assert payload["outcomes"] == {"success": 1, "upstream_non_200": 1}


def test_main_window_minutes_filters_to_recent_records(tmp_path: Path):
    log_path = tmp_path / "routes.jsonl"
    log_path.write_text(
        "\n".join(
            [
                '{"event":"route_complete","request_id":"old","route_id":"lite","ts":"2026-05-29T10:00:00Z"}',
                '{"event":"route_complete","request_id":"new","route_id":"deep","ts":"2026-05-29T10:05:00Z"}',
            ]
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/router_log_summary.py",
            str(log_path),
            "--json",
            "--window-minutes",
            "1",
        ],
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["total"] == 1
    assert payload["routes"] == {"deep": 1}


def test_contract_fixture_has_no_sensitive_payload_fields():
    fixture_text = Path("tests/samples/router_logs_contract.ndjson").read_text()

    forbidden_patterns = [
        "prompt",
        "authorization",
        "bearer ",
        "request_body",
        "raw_body",
    ]
    lower_fixture = fixture_text.lower()

    for pattern in forbidden_patterns:
        assert pattern not in lower_fixture
