from __future__ import annotations

import pytest

from scripts.preflight import (
    CheckResult,
    require_header,
    require_json_field,
    run_preflight,
    summarize_results,
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
        yield self._body


class FakeClient:
    def __init__(self):
        self.urls: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def get(self, url: str) -> FakeResponse:
        self.urls.append(url)
        if url.endswith("/ready"):
            return FakeResponse(payload={"ready": True, "components": {}})
        return FakeResponse(payload={"status": "ok"})

    def post(self, url: str, *, headers: dict, json: dict) -> FakeResponse:
        self.urls.append(url)
        return FakeResponse(
            headers={"x-router-target-model": "pro-router"},
        )

    def stream(self, method: str, url: str, *, headers: dict, json: dict) -> FakeResponse:
        self.urls.append(url)
        return FakeResponse(
            headers={"x-router-target-model": "pro-router"},
            body=b"data: first\n\n",
        )


def test_require_header_returns_pass_for_expected_header():
    result = require_header(
        name="nonstream_route",
        headers={"x-router-target-model": "pro-router"},
        key="x-router-target-model",
        expected="pro-router",
    )

    assert result == CheckResult("nonstream_route", True, "x-router-target-model=pro-router")


def test_require_header_returns_failure_for_missing_header():
    result = require_header(
        name="stream_route",
        headers={},
        key="x-router-target-model",
        expected="pro-router",
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
        api_key="test-key",
        timeout=5,
    )

    assert "http://router.local/ready" in fake_client.urls
    assert CheckResult("ready_status", True, "status=200") in results
    assert CheckResult("ready_payload", True, "ready=True") in results
