from __future__ import annotations

from scripts.e2e_litellm_entry import (
    CheckResult,
    Probe,
    apply_target_model_overrides,
    collect_logs,
    find_matching_route_log,
    find_route_log,
    format_route_failure_detail,
    parse_route_logs,
    print_progress,
    probe_elapsed_results,
    resolve_probe_expectations,
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
            '{"event":"route_complete","request_id":"req-1","target_model":"your-deep-model"}',
            '{"event":"route_error","request_id":"req-2","target_model":"your-lite-model"}',
        ]
    )

    assert parse_route_logs(logs) == [
        {"event": "route_complete", "request_id": "req-1", "target_model": "your-deep-model"},
        {"event": "route_error", "request_id": "req-2", "target_model": "your-lite-model"},
    ]


def test_parse_route_logs_unwraps_azure_containerapp_log_lines():
    logs = "\n".join(
        [
            (
                '{"TimeStamp":"2026-05-26T13:39:41Z",'
                '"Log":"{\\"event\\":\\"route_complete\\",'
                '\\"request_id\\":\\"req-1\\",'
                '\\"stream\\":false,\\"route_id\\":\\"lite\\",'
                '\\"target_model\\":\\"lite\\",\\"upstream_status\\":200}"}'
            ),
            (
                '{"TimeStamp":"2026-05-26T13:39:42Z",'
                '"Log":"28661.29, \\"duration_ms\\": 30287.47, '
                '\\"event\\": \\"route_complete\\", \\"request_id\\": \\"req-2\\", '
                '\\"stream\\": false, \\"route_id\\": \\"lite\\", '
                '\\"target_model\\": \\"lite\\", \\"upstream_status\\": 200}"}'
            ),
        ]
    )

    records = parse_route_logs(logs)

    assert [record["request_id"] for record in records] == ["req-1", "req-2"]
    assert records[1]["upstream_status"] == 200
    assert records[1]["duration_ms"] == 30287.47


def test_find_route_log_matches_request_id_and_stream_mode():
    logs = [
        {
            "event": "route_complete",
            "request_id": "req-1",
            "stream": False,
            "target_model": "your-lite-model",
        },
        {
            "event": "route_complete",
            "request_id": "req-2",
            "stream": True,
            "target_model": "your-deep-model",
        },
    ]

    assert find_route_log(logs, request_id="req-2", stream=True) == logs[1]
    assert find_route_log(logs, request_id="req-2", stream=False) is None


def test_find_matching_route_log_matches_recent_route_shape_once():
    logs = [
        {
            "event": "route_complete",
            "source_model": "intentmux",
                "route_id": "deep",
            "target_model": "your-deep-model",
            "stream": False,
            "upstream_status": 200,
        },
        {
            "event": "route_complete",
            "source_model": "intentmux",
                "route_id": "deep",
            "target_model": "your-deep-model",
            "stream": True,
            "upstream_status": 200,
        },
    ]
    used_indexes: set[int] = set()

    match = find_matching_route_log(
        logs,
        probe=Probe("deep_stream", "prompt", "deep", "your-deep-model", stream=True),
        used_indexes=used_indexes,
    )

    assert match == (1, logs[1])


def test_resolve_probe_expectations_uses_live_decision_contract(monkeypatch):
    class DecisionClient:
        def __init__(self, timeout):
            self.requests = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return None

        def post(self, url, json, headers):
            self.requests.append((url, json, headers))
            return FakeResponse(
                status_code=200,
                payload={
                    "route_id": "deep",
                    "target_model": "deep",
                },
            )

    monkeypatch.setattr("scripts.e2e_litellm_entry.httpx.Client", DecisionClient)

    probes = resolve_probe_expectations(
        [Probe("deep_nonstream", "prompt", "deep", "your-deep-model")],
        router_base_url="http://intentmux.local",
        intentmux_api_key="intent-key",
        timeout=3.0,
    )

    assert probes == [Probe("deep_nonstream", "prompt", "deep", "deep")]


def _log_line(record: dict) -> str:
    import json

    return json.dumps(record, ensure_ascii=False)


def test_validate_route_logs_strict_request_id_match():
    probe = Probe("p1", "safe prompt", "deep", "your-deep-model", stream=False)
    raw_logs = _log_line(
        {
            "event": "route_complete",
            "request_id": "rid-1",
            "stream": False,
            "source_model": "intentmux",
                "route_id": "deep",
            "target_model": "your-deep-model",
            "upstream_status": 200,
        }
    )

    results = validate_route_logs(raw_logs=raw_logs, probes=[(probe, "rid-1")])

    by_name = {result.name: result for result in results}
    assert by_name["p1_route_log_present"].detail.endswith("matched_by=request_id")
    assert by_name["route_log_match_mode"].ok is True


def test_validate_route_logs_fallback_route_shape_match():
    probe = Probe("p1", "safe prompt", "deep", "your-deep-model", stream=False)
    raw_logs = _log_line(
        {
            "event": "route_complete",
            "request_id": "other-id",
            "stream": False,
            "source_model": "intentmux",
                "route_id": "deep",
            "target_model": "your-deep-model",
            "upstream_status": 200,
        }
    )

    results = validate_route_logs(raw_logs=raw_logs, probes=[(probe, "rid-1")])

    by_name = {result.name: result for result in results}
    assert by_name["p1_route_log_present"].detail.endswith("matched_by=route_shape")
    assert by_name["route_log_match_mode"].ok is True


def test_validate_route_logs_duplicate_route_shape_records_are_not_reused():
    probes = [
        (Probe("p1", "safe prompt", "deep", "your-deep-model", stream=False), "rid-1"),
        (Probe("p2", "safe prompt", "deep", "your-deep-model", stream=False), "rid-2"),
    ]
    raw_logs = _log_line(
        {
            "event": "route_complete",
            "request_id": "other-id",
            "stream": False,
            "source_model": "intentmux",
                "route_id": "deep",
            "target_model": "your-deep-model",
            "upstream_status": 200,
        }
    )

    results = validate_route_logs(raw_logs=raw_logs, probes=probes)

    by_name = {result.name: result for result in results}
    assert by_name["p1_route_log_present"].ok is True
    assert by_name["p2_route_log_present"].ok is False
    assert by_name["p2_route_log_present"].detail.endswith("matched_by=not_found")


def test_validate_route_logs_require_request_id_match_fails_on_fallback():
    probe = Probe("p1", "safe prompt", "deep", "your-deep-model", stream=False)
    raw_logs = _log_line(
        {
            "event": "route_complete",
            "request_id": "other-id",
            "stream": False,
            "source_model": "intentmux",
                "route_id": "deep",
            "target_model": "your-deep-model",
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


def test_validate_route_logs_can_enforce_duration_budget():
    probe = Probe("p1", "safe prompt", "lite", "lite", stream=False)
    raw_logs = _log_line(
        {
            "event": "route_complete",
            "request_id": "rid-1",
            "stream": False,
            "source_model": "intentmux",
            "route_id": "lite",
            "target_model": "lite",
            "upstream_status": 200,
            "duration_ms": 30_001.0,
        }
    )

    results = validate_route_logs(
        raw_logs=raw_logs,
        probes=[(probe, "rid-1")],
        max_route_duration_ms=10_000.0,
    )

    by_name = {result.name: result for result in results}
    assert by_name["p1_route_duration"].ok is False
    assert "duration_ms=30001.0" in by_name["p1_route_duration"].detail


def test_probe_elapsed_results_enforces_client_side_budget():
    probe = Probe("p1", "prompt", "lite", "lite")

    result = probe_elapsed_results(
        probe=probe,
        elapsed_ms=12_000.0,
        max_probe_elapsed_ms=10_000.0,
    )[0]

    assert result.name == "p1_probe_elapsed"
    assert result.ok is False
    assert "elapsed_ms=12000.00" in result.detail


def test_validate_route_logs_redaction_detects_prompt_and_bearer_token_leaks():
    probe = Probe("p1", "my secret prompt", "deep", "your-deep-model", stream=False)
    raw_logs = "\n".join(
        [
            "Bearer top-secret-token",
            _log_line(
                {
                    "event": "route_complete",
                    "request_id": "rid-1",
                    "stream": False,
                    "source_model": "intentmux",
                "route_id": "deep",
                    "target_model": "your-deep-model",
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
    probe = Probe("p1", "prompt", "deep", "your-deep-model", stream=False)
    passed = FakeResponse(
        status_code=200,
        headers={"content-type": "application/json"},
        payload={"model": "intentmux"},
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
    assert fail_by_name["p1_outer_model"].detail == "model=None, expected=intentmux"


def test_validate_nonstream_probe_response_can_skip_outer_model_check():
    probe = Probe("p1", "prompt", "lite", "lite", stream=False)
    response = FakeResponse(
        status_code=200,
        headers={"content-type": "application/json"},
        payload={"model": "provider-model"},
    )

    by_name = {
        result.name: result
        for result in validate_nonstream_probe_response(
            probe=probe,
            response=response,
            expected_outer_model=None,
        )
    }

    assert by_name["p1_outer_model"].ok is True


def test_validate_nonstream_probe_response_extracts_provider_router_request_id():
    probe = Probe("p1", "prompt", "lite", "your-lite-model", stream=False)
    response = FakeResponse(
        status_code=200,
        headers={
            "content-type": "application/json",
            "llm_provider-x-router-request-id": "router-generated-1",
        },
        payload={"model": "intentmux"},
    )

    by_name = {
        result.name: result
        for result in validate_nonstream_probe_response(probe=probe, response=response)
    }

    assert by_name["p1_router_request_id"].ok is True
    assert by_name["p1_router_request_id"].detail == "request_id=router-generated-1"


def test_validate_streaming_probe_response_detects_missing_sse_marker():
    probe = Probe("p1", "prompt", "deep", "your-deep-model", stream=True)
    response = FakeResponse(status_code=200)

    pass_by_name = {
        result.name: result
        for result in validate_streaming_probe_response(
            probe=probe,
            response=response,
            body_head=b"data: chunk\n\n",
        )
    }
    fail_by_name = {
        result.name: result
        for result in validate_streaming_probe_response(
            probe=probe,
            response=response,
            body_head=b'{"delta":"x"}',
        )
    }

    assert pass_by_name["p1_sse"].ok is True
    assert fail_by_name["p1_sse"].ok is False


def test_validate_streaming_probe_response_can_require_done_marker():
    probe = Probe("p1", "prompt", "deep", "deep", stream=True)
    response = FakeResponse(status_code=200)

    incomplete = {
        result.name: result
        for result in validate_streaming_probe_response(
            probe=probe,
            response=response,
            body_head=b"data: chunk\n\n",
            require_stream_done=True,
        )
    }
    complete = {
        result.name: result
        for result in validate_streaming_probe_response(
            probe=probe,
            response=response,
            body_head=b"data: chunk\n\ndata: [DONE]\n\n",
            require_stream_done=True,
        )
    }

    assert incomplete["p1_stream_done"].ok is False
    assert complete["p1_stream_done"].ok is True


def test_apply_target_model_overrides_changes_cloud_route_targets():
    probes = [
        Probe("lite_case", "prompt", "lite", "your-lite-model"),
        Probe("deep_case", "prompt", "deep", "your-deep-model"),
    ]

    overridden = apply_target_model_overrides(
        probes,
        lite_target_model="lite",
        deep_target_model="deep",
    )

    assert [probe.expected_target_model for probe in overridden] == ["lite", "deep"]


def test_collect_logs_requires_azure_details():
    import pytest

    with pytest.raises(ValueError, match="--azure-containerapp-name"):
        collect_logs(
            source="azure",
            docker_container="unused",
            azure_containerapp_name=None,
            azure_resource_group="rg",
            tail=1,
        )


def test_run_e2e_uses_provider_router_request_id_for_strict_log_match(monkeypatch):
    monkeypatch.setattr(
        "scripts.e2e_litellm_entry.httpx.Client",
        FakeClient,
    )

    def fake_run_probe(**kwargs):
        probe = kwargs["probe"]
        return [
            CheckResult(f"{probe.name}_status", True, "status=200"),
            CheckResult(
                f"{probe.name}_router_request_id",
                True,
                f"request_id=router-{probe.name}",
            ),
        ]

    monkeypatch.setattr("scripts.e2e_litellm_entry.run_probe", fake_run_probe)
    monkeypatch.setattr(
        "scripts.e2e_litellm_entry.docker_logs",
        lambda container, tail: "\n".join(
            _log_line(
                {
                    "event": "route_complete",
                    "request_id": f"router-{probe.name}",
                    "stream": probe.stream,
                    "source_model": "intentmux",
                    "route_id": probe.expected_route,
                    "target_model": probe.expected_target_model,
                    "upstream_status": 200,
                }
            )
            for probe in [
                Probe("deep_nonstream", "prompt", "deep", "your-deep-model"),
                Probe("deep_stream", "prompt", "deep", "your-deep-model", stream=True),
                Probe("lite_nonstream", "prompt", "lite", "your-lite-model"),
            ]
        ),
    )

    results = run_e2e(
        litellm_base_url="http://litellm.local",
        api_key="test-key",
        timeout=3.0,
        log_container="unused",
        log_tail=10,
        skip_log_check=False,
        require_request_id_log_match=True,
        progress=None,
    )

    by_name = {result.name: result for result in results}
    assert by_name["route_log_match_mode"].ok is True
    assert "strict_request_id_matches=3/3" in by_name["route_log_match_mode"].detail


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
        "deep_nonstream_stub",
        "deep_stream_stub",
        "lite_nonstream_stub",
    ]
    assert [line.split("\t")[:2] for line in progress] == [
        ["RUN", "deep_nonstream"],
        ["RUN", "deep_stream"],
        ["RUN", "lite_nonstream"],
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
                "source_model": "intentmux",
                "route_id": "deep",
                "target_model": "your-deep-model",
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
    assert by_name["deep_nonstream_route_log_present"].ok is False
    assert "skipped_due_to_failed_probe" in by_name["deep_nonstream_route_log_present"].detail
