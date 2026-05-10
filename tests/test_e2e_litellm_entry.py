from __future__ import annotations

from scripts.e2e_litellm_entry import (
    CheckResult,
    Probe,
    find_matching_route_log,
    find_route_log,
    format_route_failure_detail,
    parse_route_logs,
    print_progress,
    run_e2e,
    validate_nonstream_probe_response,
    validate_route_logs,
    validate_streaming_probe_response,
)


class FakeClient:
    def __init__(self, timeout):
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        payload: dict | None = None,
    ):
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


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
                "route_id": "strong",
            "target_model": "pro-router",
            "stream": False,
            "upstream_status": 200,
        },
        {
            "event": "route_complete",
            "source_model": "semantic-router",
                "route_id": "strong",
            "target_model": "pro-router",
            "stream": True,
            "upstream_status": 200,
        },
    ]
    used_indexes: set[int] = set()

    match = find_matching_route_log(
        logs,
        probe=Probe("pro_stream", "prompt", "strong", "pro-router", stream=True),
        used_indexes=used_indexes,
    )

    assert match == (1, logs[1])


def _log_line(record: dict) -> str:
    import json

    return json.dumps(record, ensure_ascii=False)


def test_validate_route_logs_strict_request_id_match():
    probe = Probe("p1", "safe prompt", "strong", "pro-router", stream=False)
    raw_logs = _log_line(
        {
            "event": "route_complete",
            "request_id": "rid-1",
            "stream": False,
            "source_model": "semantic-router",
                "route_id": "strong",
            "target_model": "pro-router",
            "upstream_status": 200,
        }
    )

    results = validate_route_logs(raw_logs=raw_logs, probes=[(probe, "rid-1")])

    by_name = {result.name: result for result in results}
    assert by_name["p1_route_log_present"].detail.endswith("matched_by=request_id")
    assert by_name["route_log_match_mode"].ok is True


def test_validate_route_logs_fallback_route_shape_match():
    probe = Probe("p1", "safe prompt", "strong", "pro-router", stream=False)
    raw_logs = _log_line(
        {
            "event": "route_complete",
            "request_id": "other-id",
            "stream": False,
            "source_model": "semantic-router",
                "route_id": "strong",
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
        (Probe("p1", "safe prompt", "strong", "pro-router", stream=False), "rid-1"),
        (Probe("p2", "safe prompt", "strong", "pro-router", stream=False), "rid-2"),
    ]
    raw_logs = _log_line(
        {
            "event": "route_complete",
            "request_id": "other-id",
            "stream": False,
            "source_model": "semantic-router",
                "route_id": "strong",
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
    probe = Probe("p1", "safe prompt", "strong", "pro-router", stream=False)
    raw_logs = _log_line(
        {
            "event": "route_complete",
            "request_id": "other-id",
            "stream": False,
            "source_model": "semantic-router",
                "route_id": "strong",
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
    probe = Probe("p1", "my secret prompt", "strong", "pro-router", stream=False)
    raw_logs = "\n".join(
        [
            "Bearer top-secret-token",
            _log_line(
                {
                    "event": "route_complete",
                    "request_id": "rid-1",
                    "stream": False,
                    "source_model": "semantic-router",
                "route_id": "strong",
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


def test_validate_nonstream_probe_response_detects_missing_model_field():
    probe = Probe("p1", "prompt", "strong", "pro-router", stream=False)
    passed = FakeResponse(
        status_code=200,
        headers={"content-type": "application/json"},
        payload={"model": "semantic-router"},
    )
    failed = FakeResponse(
        status_code=200,
        headers={"content-type": "application/json"},
        payload={"id": "chatcmpl-1"},
    )

    pass_by_name = {
        result.name: result
        for result in validate_nonstream_probe_response(probe=probe, response=passed)
    }
    fail_by_name = {
        result.name: result
        for result in validate_nonstream_probe_response(probe=probe, response=failed)
    }

    assert pass_by_name["p1_outer_model"].ok is True
    assert fail_by_name["p1_outer_model"].ok is False
    assert fail_by_name["p1_outer_model"].detail == "model=None"


def test_validate_streaming_probe_response_detects_missing_sse_marker():
    probe = Probe("p1", "prompt", "strong", "pro-router", stream=True)
    response = FakeResponse(status_code=200)

    pass_by_name = {
        result.name: result
        for result in validate_streaming_probe_response(
            probe=probe,
            response=response,
            first_chunk=b"data: chunk\n\n",
        )
    }
    fail_by_name = {
        result.name: result
        for result in validate_streaming_probe_response(
            probe=probe,
            response=response,
            first_chunk=b'{"delta":"x"}',
        )
    }

    assert pass_by_name["p1_sse"].ok is True
    assert fail_by_name["p1_sse"].ok is False


def test_format_route_failure_detail_is_stable():
    detail = format_route_failure_detail(
        {"event": "route_error", "error_type": "upstream_timeout"}
    )

    assert detail == "event=route_error, error_type=upstream_timeout"


def test_run_e2e_emits_progress_before_each_probe(monkeypatch):
    progress: list[str] = []

    monkeypatch.setattr(
        "scripts.e2e_litellm_entry.httpx.Client",
        FakeClient,
    )
    monkeypatch.setattr(
        "scripts.e2e_litellm_entry.run_probe",
        lambda **kwargs: [CheckResult(f"{kwargs['probe'].name}_stub", True, "ok")],
    )

    results = run_e2e(
        litellm_base_url="http://litellm.local",
        api_key="test-key",
        timeout=3.0,
        log_container="unused",
        log_tail=1,
        skip_log_check=True,
        require_request_id_log_match=False,
        progress=progress.append,
    )

    assert [result.name for result in results] == [
        "pro_nonstream_stub",
        "pro_stream_stub",
        "cheap_nonstream_stub",
    ]
    assert [line.split("\t")[:2] for line in progress] == [
        ["RUN", "pro_nonstream"],
        ["RUN", "pro_stream"],
        ["RUN", "cheap_nonstream"],
    ]


def test_print_progress_flushes_output(monkeypatch):
    calls = []

    monkeypatch.setattr(
        "builtins.print",
        lambda line, *, flush: calls.append((line, flush)),
    )

    print_progress("RUN\tprobe")

    assert calls == [("RUN\tprobe", True)]


def test_run_e2e_does_not_shape_match_logs_for_failed_probe(monkeypatch):
    monkeypatch.setattr(
        "scripts.e2e_litellm_entry.httpx.Client",
        FakeClient,
    )
    monkeypatch.setattr(
        "scripts.e2e_litellm_entry.run_probe",
        lambda **kwargs: [
            CheckResult(f"{kwargs['probe'].name}_status", False, "status=400")
        ],
    )
    monkeypatch.setattr(
        "scripts.e2e_litellm_entry.docker_logs",
        lambda container, tail: _log_line(
            {
                "event": "route_complete",
                "request_id": "old-request",
                "stream": False,
                "source_model": "semantic-router",
                "route_id": "strong",
                "target_model": "pro-router",
                "upstream_status": 200,
            }
        ),
    )

    results = run_e2e(
        litellm_base_url="http://litellm.local",
        api_key="test-key",
        timeout=3.0,
        log_container="unused",
        log_tail=1,
        skip_log_check=False,
        require_request_id_log_match=False,
        progress=None,
    )

    by_name = {result.name: result for result in results}
    assert by_name["pro_nonstream_route_log_present"].ok is False
    assert "skipped_due_to_failed_probe" in by_name["pro_nonstream_route_log_present"].detail
