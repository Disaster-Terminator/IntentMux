from __future__ import annotations

from scripts.e2e_litellm_entry import (
    Probe,
    find_matching_route_log,
    find_route_log,
    parse_route_logs,
)


def test_parse_route_logs_ignores_non_json_lines():
    logs = "\n".join(
        [
            'INFO:     127.0.0.1:1 - "GET /health HTTP/1.1" 200 OK',
            '{"event":"route_complete","request_id":"req-1","target_model":"pro-router"}',
            '{"event":"route_error","request_id":"req-2","target_model":"cheap-router"}',
        ]
    )

    assert parse_route_logs(logs) == [
        {"event": "route_complete", "request_id": "req-1", "target_model": "pro-router"},
        {"event": "route_error", "request_id": "req-2", "target_model": "cheap-router"},
    ]


def test_find_route_log_matches_request_id_and_stream_mode():
    logs = [
        {
            "event": "route_complete",
            "request_id": "req-1",
            "stream": False,
            "target_model": "cheap-router",
        },
        {
            "event": "route_complete",
            "request_id": "req-2",
            "stream": True,
            "target_model": "pro-router",
        },
    ]

    assert find_route_log(logs, request_id="req-2", stream=True) == logs[1]
    assert find_route_log(logs, request_id="req-2", stream=False) is None


def test_find_matching_route_log_matches_recent_route_shape_once():
    logs = [
        {
            "event": "route_complete",
            "source_model": "semantic-router",
            "target_model": "pro-router",
            "stream": False,
            "upstream_status": 200,
        },
        {
            "event": "route_complete",
            "source_model": "semantic-router",
            "target_model": "pro-router",
            "stream": True,
            "upstream_status": 200,
        },
    ]
    used_indexes: set[int] = set()

    match = find_matching_route_log(
        logs,
        probe=Probe("pro_stream", "prompt", "pro-router", stream=True),
        used_indexes=used_indexes,
    )

    assert match == (1, logs[1])
