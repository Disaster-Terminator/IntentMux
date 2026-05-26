from __future__ import annotations

import pytest

from scripts.preflight import (
    CheckResult,
    main,
    require_header,
    require_json_field,
    run_preflight,
    summarize_results,
    validate_nonstream_chat_response,
    validate_streaming_sse_response,
)


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        payload: dict | None = None,
        headers: dict[str, str] | None = None,
        body: bytes = b"",
    ):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}
        self._body = body

    def json(self) -> dict:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def iter_bytes(self):
        yield from self._body.splitlines(keepends=True)


class FakeClient:
    def __init__(self):
        self.urls: list[str] = []
        self.get_headers: list[dict[str, str]] = []
        self.post_headers: list[dict[str, str]] = []
        self.post_payloads: list[dict] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def get(self, url: str, *, headers: dict[str, str] | None = None) -> FakeResponse:
        self.urls.append(url)
        self.get_headers.append(headers or {})
        if url.endswith("/ready"):
            return FakeResponse(payload={"ready": True, "components": {}})
        return FakeResponse(payload={"status": "ok"})

    def post(self, url: str, *, headers: dict, json: dict) -> FakeResponse:
        self.urls.append(url)
        self.post_headers.append(headers)
        self.post_payloads.append(json)
        return FakeResponse(
            headers={"x-router-target-model": "your-deep-model"},
        )

    def stream(self, method: str, url: str, *, headers: dict, json: dict) -> FakeResponse:
        self.urls.append(url)
        self.post_headers.append(headers)
        self.post_payloads.append(json)
        return FakeResponse(
            headers={"x-router-target-model": "your-deep-model"},
            body=b"data: first\n\ndata: [DONE]\n\n",
        )


class DegradedReadyClient(FakeClient):
    def get(self, url: str, *, headers: dict[str, str] | None = None) -> FakeResponse:
        self.urls.append(url)
        self.get_headers.append(headers or {})
        if url.endswith("/ready"):
            return FakeResponse(
                status_code=503,
                payload={
                    "ready": False,
                    "components": {
                        "router": {"ok": True, "detail": None},
                        "litellm": {"ok": True, "detail": "status=401 auth_required"},
                        "embedding": {"ok": False, "detail": "ConnectError"},
                    },
                },
            )
        return FakeResponse(payload={"status": "ok"})


class FlakyReadyClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.ready_calls = 0

    def get(self, url: str, *, headers: dict[str, str] | None = None) -> FakeResponse:
        self.urls.append(url)
        self.get_headers.append(headers or {})
        if url.endswith("/ready"):
            self.ready_calls += 1
            if self.ready_calls == 1:
                return FakeResponse(
                    status_code=503,
                    payload={
                        "ready": False,
                        "components": {
                            "embedding": {"ok": False, "detail": "ReadTimeout"},
                        },
                    },
                )
            return FakeResponse(payload={"ready": True, "components": {}})
        return FakeResponse(payload={"status": "ok"})


class AuthRejectingClient(FakeClient):
    def get(self, url: str, *, headers: dict[str, str] | None = None) -> FakeResponse:
        self.urls.append(url)
        headers = headers or {}
        self.get_headers.append(headers)
        if not headers and (url.endswith("/ready") or url.endswith("/v1/models")):
            return FakeResponse(status_code=401, payload={"error": "unauthorized"})
        if url.endswith("/ready"):
            return FakeResponse(payload={"ready": True, "components": {}})
        return FakeResponse(payload={"status": "ok"})

    def post(self, url: str, *, headers: dict, json: dict) -> FakeResponse:
        self.urls.append(url)
        self.post_headers.append(headers)
        self.post_payloads.append(json)
        if not headers:
            return FakeResponse(status_code=401, payload={"error": "unauthorized"})
        return FakeResponse(headers={"x-router-target-model": "your-deep-model"})


def test_require_header_returns_pass_for_expected_header():
    result = require_header(
        name="nonstream_route",
        headers={"x-router-target-model": "your-deep-model"},
        key="x-router-target-model",
        expected="your-deep-model",
    )

    assert result == CheckResult("nonstream_route", True, "x-router-target-model=your-deep-model")


def test_require_header_returns_failure_for_missing_header():
    result = require_header(
        name="stream_route",
        headers={},
        key="x-router-target-model",
        expected="your-deep-model",
    )

    assert result.ok is False
    assert "missing" in result.detail


def test_require_json_field_validates_health_payload():
    result = require_json_field(
        name="health",
        payload={"status": "ok"},
        key="status",
        expected="ok",
    )

    assert result.ok is True


def test_summarize_results_exits_nonzero_when_any_check_fails():
    results = [
        CheckResult("health", True, "ok"),
        CheckResult("stream", False, "wrong route"),
    ]

    with pytest.raises(SystemExit) as exc:
        summarize_results(results)

    assert exc.value.code == 1


def test_run_preflight_checks_layered_readiness(monkeypatch):
    fake_client = FakeClient()

    monkeypatch.setattr(
        "scripts.preflight.httpx.Client",
        lambda timeout: fake_client,
    )

    results = run_preflight(
        "http://router.local",
        intentmux_api_key="test-key",
        timeout=5,
        ready_attempts=1,
        ready_interval=0,
    )

    assert "http://router.local/ready" in fake_client.urls
    assert fake_client.get_headers == [
        {},
        {"Authorization": "Bearer test-key"},
    ]
    assert fake_client.post_headers == [
        {"Authorization": "Bearer test-key"},
        {"Authorization": "Bearer test-key"},
    ]
    assert [payload["model"] for payload in fake_client.post_payloads] == ["auto", "auto"]
    assert CheckResult("ready_status", True, "status=200") in results
    assert CheckResult("ready_payload", True, "ready=True") in results


def test_run_preflight_can_probe_legacy_sidecar_entry(monkeypatch):
    fake_client = FakeClient()

    monkeypatch.setattr(
        "scripts.preflight.httpx.Client",
        lambda timeout: fake_client,
    )

    run_preflight(
        "http://router.local",
        intentmux_api_key=None,
        timeout=5,
        ready_attempts=1,
        ready_interval=0,
        model="intentmux",
    )

    assert [payload["model"] for payload in fake_client.post_payloads] == [
        "intentmux",
        "intentmux",
    ]


def test_run_preflight_reports_degraded_readiness_components(monkeypatch):
    fake_client = DegradedReadyClient()

    monkeypatch.setattr(
        "scripts.preflight.httpx.Client",
        lambda timeout: fake_client,
    )

    results = run_preflight(
        "http://router.local",
        intentmux_api_key="test-key",
        timeout=5,
        ready_attempts=1,
        ready_interval=0,
    )

    assert CheckResult("ready_status", False, "status=503") in results
    assert CheckResult(
        "ready_payload",
        False,
        "ready=False degraded=embedding:ConnectError",
    ) in results


def test_run_preflight_retries_transient_readiness_failure(monkeypatch):
    fake_client = FlakyReadyClient()

    monkeypatch.setattr(
        "scripts.preflight.httpx.Client",
        lambda timeout: fake_client,
    )

    results = run_preflight(
        "http://router.local",
        intentmux_api_key="test-key",
        timeout=5,
        ready_attempts=2,
        ready_interval=0,
    )

    assert fake_client.ready_calls == 2
    assert CheckResult("ready_status", True, "status=200") in results
    assert CheckResult("ready_payload", True, "ready=True") in results


def test_run_preflight_can_require_unauthenticated_rejections(monkeypatch):
    fake_client = AuthRejectingClient()

    monkeypatch.setattr(
        "scripts.preflight.httpx.Client",
        lambda timeout: fake_client,
    )

    results = run_preflight(
        "http://router.local",
        intentmux_api_key="test-key",
        timeout=5,
        ready_attempts=1,
        ready_interval=0,
        require_unauth_rejected=True,
    )

    assert CheckResult("unauth_ready", True, "status=401") in results
    assert CheckResult("unauth_models", True, "status=401") in results
    assert CheckResult("unauth_chat", True, "status=401") in results
    assert fake_client.post_headers == [
        {},
        {"Authorization": "Bearer test-key"},
        {"Authorization": "Bearer test-key"},
    ]


def test_run_preflight_omits_authorization_when_intentmux_api_key_is_unset(monkeypatch):
    fake_client = FakeClient()

    monkeypatch.setattr(
        "scripts.preflight.httpx.Client",
        lambda timeout: fake_client,
    )

    run_preflight(
        "http://router.local",
        intentmux_api_key=None,
        timeout=5,
        ready_attempts=1,
        ready_interval=0,
    )

    assert fake_client.post_headers == [{}, {}]


def test_preflight_accepts_deprecated_api_key_alias(monkeypatch, capsys):
    fake_client = FakeClient()

    monkeypatch.setattr(
        "scripts.preflight.httpx.Client",
        lambda timeout: fake_client,
    )

    main(
        [
            "--router-base-url",
            "http://router.local",
            "--api-key",
            "legacy-key",
            "--ready-attempts",
            "1",
            "--ready-interval",
            "0",
        ]
    )

    assert fake_client.post_headers == [
        {"Authorization": "Bearer legacy-key"},
        {"Authorization": "Bearer legacy-key"},
    ]
    assert "deprecated" in capsys.readouterr().err


def test_validate_nonstream_chat_response_fixture_pass_and_fail():
    passed = FakeResponse(
        status_code=200,
        headers={"x-router-target-model": "your-deep-model"},
    )
    failed = FakeResponse(
        status_code=200,
        headers={},
    )

    pass_by_name = {r.name: r for r in validate_nonstream_chat_response(passed)}
    fail_by_name = {r.name: r for r in validate_nonstream_chat_response(failed)}

    assert pass_by_name["nonstream_status"].ok is True
    assert pass_by_name["nonstream_route"].ok is True
    assert fail_by_name["nonstream_route"].ok is False
    assert "missing header x-router-target-model" == fail_by_name["nonstream_route"].detail


def test_validate_nonstream_chat_response_can_assert_expected_target_model():
    response = FakeResponse(
        status_code=200,
        headers={"x-router-target-model": "your-deep-model"},
    )

    passed = {
        r.name: r
        for r in validate_nonstream_chat_response(
            response,
            expected_target_model="your-deep-model",
        )
    }
    failed = {
        r.name: r
        for r in validate_nonstream_chat_response(
            response,
            expected_target_model="other-model",
        )
    }

    assert passed["nonstream_route"].ok is True
    assert failed["nonstream_route"].ok is False


def test_validate_streaming_sse_response_fixture_pass_and_fail():
    response = FakeResponse(status_code=200, headers={"x-router-target-model": "your-deep-model"})

    pass_by_name = {
        r.name: r
        for r in validate_streaming_sse_response(
            response,
            b"data: {\"x\":1}\n\ndata: [DONE]\n\n",
        )
    }
    fail_by_name = {
        r.name: r for r in validate_streaming_sse_response(response, b"{\"x\":1}")
    }
    incomplete_by_name = {
        r.name: r
        for r in validate_streaming_sse_response(response, b"data: {\"x\":1}\n\n")
    }

    assert pass_by_name["stream_body"].ok is True
    assert fail_by_name["stream_body"].ok is False
    assert fail_by_name["stream_body"].detail == "starts_with_data=False"
    assert pass_by_name["stream_complete"].ok is True
    assert incomplete_by_name["stream_complete"].ok is False
    assert incomplete_by_name["stream_complete"].detail == "has_done=False"


def test_run_preflight_reads_bounded_stream_until_done(monkeypatch):
    fake_client = FakeClient()

    monkeypatch.setattr(
        "scripts.preflight.httpx.Client",
        lambda timeout: fake_client,
    )

    results = run_preflight(
        "http://router.local",
        intentmux_api_key=None,
        timeout=5,
        ready_attempts=1,
        ready_interval=0,
    )

    assert CheckResult("stream_complete", True, "has_done=True") in results
