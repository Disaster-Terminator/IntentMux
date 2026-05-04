from __future__ import annotations

from scripts.e2e_litellm_entry import (
    Probe,
    find_matching_route_log,
    find_route_log,
    parse_route_logs,
    validate_route_logs,
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


def _log_line(record: dict) -> str:
    import json

    return json.dumps(record, ensure_ascii=False)


def test_validate_route_logs_strict_request_id_match():
    probe = Probe("p1", "safe prompt", "pro-router", stream=False)
    raw_logs = _log_line(
        {
            "event": "route_complete",
            "request_id": "rid-1",
            "stream": False,
            "source_model": "semantic-router",
            "target_model": "pro-router",
            "upstream_status": 200,
        }
    )
    results = validate_route_logs(raw_logs=raw_logs, probes=[(probe, "rid-1")])
    by_name = {result.name: result for result in results}
    assert by_name["p1_route_log_present"].detail.endswith("matched_by=request_id")
    assert by_name["route_log_match_mode"].ok is True


def test_validate_route_logs_fallback_route_shape_match():
    probe = Probe("p1", "safe prompt", "pro-router", stream=False)
    raw_logs = _log_line(
        {
            "event": "route_complete",
            "request_id": "other-id",
            "stream": False,
            "source_model": "semantic-router",
            "target_model": "pro-router",
            "upstream_status": 200,
        }
    )
    results = validate_route_logs(raw_logs=raw_logs, probes=[(probe, "rid-1")])
    by_name = {result.name: result for result in results}
    assert by_name["p1_route_log_present"].detail.endswith("matched_by=route_shape")
    assert by_name["route_log_match_mode"].ok is True


def test_validate_route_logs_duplicate_route_shape_records_are_not_reused():
    probes = [
        (Probe("p1", "safe prompt", "pro-router", stream=False), "rid-1"),
        (Probe("p2", "safe prompt", "pro-router", stream=False), "rid-2"),
    ]
    raw_logs = _log_line(
        {
            "event": "route_complete",
            "request_id": "other-id",
            "stream": False,
            "source_model": "semantic-router",
            "target_model": "pro-router",
            "upstream_status": 200,
        }
    )
    results = validate_route_logs(raw_logs=raw_logs, probes=probes)
    by_name = {result.name: result for result in results}
    assert by_name["p1_route_log_present"].ok is True
    assert by_name["p2_route_log_present"].ok is False
    assert by_name["p2_route_log_present"].detail.endswith("matched_by=not_found")


def test_validate_route_logs_require_request_id_match_fails_on_fallback():
    probe = Probe("p1", "safe prompt", "pro-router", stream=False)
    raw_logs = _log_line(
        {
            "event": "route_complete",
            "request_id": "other-id",
            "stream": False,
            "source_model": "semantic-router",
            "target_model": "pro-router",
            "upstream_status": 200,
        }
    )
    results = validate_route_logs(
        raw_logs=raw_logs,
        probes=[(probe, "rid-1")],
        require_request_id_log_match=True,
    )
    by_name = {result.name: result for result in results}
    assert by_name["route_log_match_mode"].ok is False


def test_validate_route_logs_redaction_detects_prompt_and_bearer_token_leaks():
    probe = Probe("p1", "my secret prompt", "pro-router", stream=False)
    raw_logs = "\n".join(
        [
            "Bearer top-secret-token",
            _log_line(
                {
                    "event": "route_complete",
                    "request_id": "rid-1",
                    "stream": False,
                    "source_model": "semantic-router",
                    "target_model": "pro-router",
                    "upstream_status": 200,
                }
            ),
            "my secret prompt",
        ]
    )
    results = validate_route_logs(raw_logs=raw_logs, probes=[(probe, "rid-1")])
    by_name = {result.name: result for result in results}
    assert by_name["log_redaction"].ok is False
