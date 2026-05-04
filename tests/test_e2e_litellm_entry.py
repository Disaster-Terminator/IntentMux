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


def test_validate_route_logs_strict_request_id_match():
    probe = Probe("pro_nonstream", "safe prompt", "pro-router", stream=False)
    request_id = "req-strict"
    raw_logs = (
        '{"event":"route_complete","request_id":"req-strict","stream":false,'
        '"source_model":"semantic-router","target_model":"pro-router","upstream_status":200}'
    )

    results = validate_route_logs(raw_logs=raw_logs, probes=[(probe, request_id)])
    result_map = {r.name: r for r in results}

    assert result_map["pro_nonstream_route_log_present"].detail.endswith(
        "matched_by=request_id"
    )
    assert result_map["pro_nonstream_route_log_match_quality"].ok is True
    assert result_map["route_log_request_id_strict_all"].ok is True


def test_validate_route_logs_fallback_route_shape_match():
    probe = Probe("pro_nonstream", "safe prompt", "pro-router", stream=False)
    raw_logs = (
        '{"event":"route_complete","request_id":"other","stream":false,'
        '"source_model":"semantic-router","target_model":"pro-router","upstream_status":200}'
    )

    results = validate_route_logs(raw_logs=raw_logs, probes=[(probe, "req-miss")])
    result_map = {r.name: r for r in results}

    assert result_map["pro_nonstream_route_log_present"].detail.endswith(
        "matched_by=route_shape"
    )
    assert result_map["pro_nonstream_route_log_match_quality"].ok is True
    assert result_map["route_log_request_id_strict_all"].ok is False
    assert result_map["route_log_request_id_strict_required"].ok is True


def test_validate_route_logs_duplicate_route_shape_records_not_reused():
    probes = [
        (Probe("probe_a", "safe prompt a", "pro-router", stream=False), "req-a"),
        (Probe("probe_b", "safe prompt b", "pro-router", stream=False), "req-b"),
    ]
    raw_logs = (
        '{"event":"route_complete","request_id":"other","stream":false,'
        '"source_model":"semantic-router","target_model":"pro-router","upstream_status":200}'
    )

    results = validate_route_logs(raw_logs=raw_logs, probes=probes)
    result_map = {r.name: r for r in results}

    assert result_map["probe_a_route_log_present"].ok is True
    assert result_map["probe_b_route_log_present"].ok is False
    assert result_map["probe_b_route_log_present"].detail.endswith("matched_by=not_found")


def test_validate_route_logs_require_request_id_log_match_enforced():
    probe = Probe("cheap_nonstream", "safe prompt", "cheap-router", stream=False)
    raw_logs = (
        '{"event":"route_complete","request_id":"different","stream":false,'
        '"source_model":"semantic-router","target_model":"cheap-router","upstream_status":200}'
    )

    results = validate_route_logs(
        raw_logs=raw_logs,
        probes=[(probe, "req-expected")],
        require_request_id_log_match=True,
    )
    result_map = {r.name: r for r in results}

    assert result_map["cheap_nonstream_route_log_match_quality"].ok is False
    assert result_map["route_log_request_id_strict_required"].ok is False


def test_validate_route_logs_redaction_detects_prompt_and_bearer_leak():
    probe = Probe("free_probe_nonstream", "super secret prompt", "free-probe-router")
    raw_logs = "Bearer sk-test\nsuper secret prompt"

    results = validate_route_logs(raw_logs=raw_logs, probes=[(probe, "req-1")])
    result_map = {r.name: r for r in results}

    assert result_map["log_redaction"].ok is False
