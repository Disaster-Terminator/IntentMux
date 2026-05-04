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


MIXED_LOG_FIXTURE = """INFO:     127.0.0.1:1 - \"GET /health HTTP/1.1\" 200 OK
INFO:     127.0.0.1:2 - \"POST /v1/chat/completions HTTP/1.1\" 200 OK
2026-05-04T01:02:03Z router {\"event\":\"route_complete\",\"target_model\":\"cheap-router\",\"reason\":\"embedding\",\"stream\":false,\"duration_ms\":310}
2026-05-04T01:02:05Z router {\"event\":\"route_error\",\"target_model\":\"pro-router\",\"reason\":\"hard_rule\",\"stream\":true,\"error_type\":\"UpstreamStatusError\",\"upstream_status\":503,\"duration_ms\":1550}
2026-05-04T01:02:06Z router {\"event\":\"route_complete\",\"target_model\":\"pro-router\",\"reason\":\"hard_rule\",\"stream\":true,\"duration_ms\":250}
2026-05-04T01:02:08Z router {\"event\":\"startup\",\"status\":\"ok\"}
2026-05-04T01:02:09Z router {\"target_model\":\"missing-event-model\",\"stream\":true}
2026-05-04T01:02:10Z router {\"event\":\"route_error\",
"""

ACCESS_ONLY_FIXTURE = """INFO:     127.0.0.1:11 - \"GET /health HTTP/1.1\" 200 OK
INFO:     127.0.0.1:12 - \"GET /ready HTTP/1.1\" 200 OK
INFO:     127.0.0.1:13 - \"POST /v1/chat/completions HTTP/1.1\" 200 OK
"""


def test_access_log_lines_without_json_are_ignored_silently():
    diagnostics = ParseDiagnostics()

    records = list(parse_route_records(ACCESS_ONLY_FIXTURE.splitlines(), diagnostics))

    assert records == []
    assert diagnostics == ParseDiagnostics()


def test_parser_and_summary_cover_route_shapes_and_diagnostics():
    diagnostics = ParseDiagnostics()
    records = list(parse_route_records(MIXED_LOG_FIXTURE.splitlines(), diagnostics=diagnostics))

    assert [record["event"] for record in records] == [
        "route_complete",
        "route_error",
        "route_complete",
    ]

    summary = summarize_records(records, parse_diagnostics=diagnostics)
    assert summary.total == 3
    assert summary.completed == 2
    assert summary.errors == 1
    assert summary.streams == 2
    assert summary.nonstreams == 1
    assert summary.targets == {"cheap-router": 1, "pro-router": 2}
    assert summary.reasons == {"embedding": 1, "hard_rule": 2}
    assert summary.error_types == {"UpstreamStatusError": 1}
    assert summary.upstream_statuses == {"503": 1}
    assert summary.parse_diagnostics.malformed_json_lines == 1
    assert summary.parse_diagnostics.missing_event_records == 1
    assert summary.parse_diagnostics.unknown_event_records == 1


def test_text_summary_includes_ignored_records_diagnostics_line():
    diagnostics = ParseDiagnostics(1, 2, 3)
    summary = summarize_records([], parse_diagnostics=diagnostics)

    assert format_summary(summary).endswith(
        "ignored_records: malformed_json=1, missing_event=2, unknown_event=3"
    )


def test_json_format_output_is_machine_readable_and_stable_keys():
    diagnostics = ParseDiagnostics(malformed_json_lines=1, missing_event_records=1, unknown_event_records=1)
    summary = summarize_records(
        list(parse_route_records(MIXED_LOG_FIXTURE.splitlines())),
        parse_diagnostics=diagnostics,
    )

    text = format_summary_json(summary)
    payload = json.loads(text)

    assert payload["ignored_records"] == {
        "malformed_json": 1,
        "missing_event": 1,
        "unknown_event": 1,
    }
    assert sorted(payload.keys()) == [
        "error_types",
        "ignored_records",
        "max_duration_ms",
        "nonstreams",
        "reasons",
        "route_complete",
        "route_error",
        "streams",
        "targets",
        "total",
        "upstream_statuses",
    ]


def test_cli_json_shortcut_matches_output_json_mode():
    output_json = subprocess.run(
        [sys.executable, "scripts/router_log_summary.py", "--output", "json"],
        input=MIXED_LOG_FIXTURE,
        text=True,
        capture_output=True,
        check=True,
    )
    shortcut_json = subprocess.run(
        [sys.executable, "scripts/router_log_summary.py", "--json"],
        input=MIXED_LOG_FIXTURE,
        text=True,
        capture_output=True,
        check=True,
    )

    assert json.loads(shortcut_json.stdout) == json.loads(output_json.stdout)
