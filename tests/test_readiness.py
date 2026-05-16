from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from router.config import RouteSpec, RouterSettings
from router.app import create_app
from router.readiness import (
    ComponentStatus,
    ReadinessChecker,
    ReadinessReport,
    litellm_status_from_code,
)
from router.routing import RoutingDecision


class FakeRouter:
    async def decide(self, request_json):
        return RoutingDecision("lite-upstream", "test", rewrite=True, source_model="semantic-router")


class FakeProxy:
    pass


@dataclass
class FakeReadinessChecker:
    report: ReadinessReport

    async def check(self) -> ReadinessReport:
        return self.report


def test_ready_returns_200_when_all_components_are_ready():
    app = create_app(
        router=FakeRouter(),
        proxy=FakeProxy(),
        readiness_checker=FakeReadinessChecker(
            ReadinessReport(
                ready=True,
                components={
                    "router": ComponentStatus(ok=True),
                    "litellm": ComponentStatus(ok=True, detail="status=200"),
                    "embedding": ComponentStatus(ok=True, detail="status=200"),
                },
            )
        ),
    )

    response = TestClient(app).get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "ready": True,
        "components": {
            "router": {"ok": True, "detail": None},
            "litellm": {"ok": True, "detail": "status=200"},
            "embedding": {"ok": True, "detail": "status=200"},
        },
    }


def test_ready_returns_503_when_any_component_is_degraded():
    app = create_app(
        router=FakeRouter(),
        proxy=FakeProxy(),
        readiness_checker=FakeReadinessChecker(
            ReadinessReport(
                ready=False,
                components={
                    "router": ComponentStatus(ok=True),
                    "litellm": ComponentStatus(ok=False, detail="timeout"),
                    "embedding": ComponentStatus(ok=True, detail="status=200"),
                },
            )
        ),
    )

    response = TestClient(app).get("/ready")

    assert response.status_code == 503
    assert response.json()["ready"] is False
    assert response.json()["components"]["litellm"] == {
        "ok": False,
        "detail": "timeout",
    }


def test_litellm_status_treats_auth_required_as_reachable():
    assert litellm_status_from_code(401) == ComponentStatus(
        ok=True,
        detail="status=401 auth_required",
    )
    assert litellm_status_from_code(403) == ComponentStatus(
        ok=True,
        detail="status=403 auth_required",
    )
    assert litellm_status_from_code(503) == ComponentStatus(
        ok=False,
        detail="status=503",
    )


def test_litellm_status_rejects_non_auth_client_errors():
    assert litellm_status_from_code(400) == ComponentStatus(
        ok=False,
        detail="status=400",
    )
    assert litellm_status_from_code(404) == ComponentStatus(
        ok=False,
        detail="status=404",
    )


def test_router_readiness_reports_route_bank_and_utterance_counts():
    settings = RouterSettings(
        routes={
            "fast": RouteSpec(description="low risk", utterances=["a", "b"]),
            "strong": RouteSpec(description="high risk", utterances=["c"]),
        },
        route_bank_loaded=True,
    )

    status = ReadinessChecker(settings).check_router()

    assert status == ComponentStatus(
        ok=True,
        detail="route_bank_loaded=true route_utterances=fast:2,strong:1",
    )


@pytest.mark.asyncio
async def test_embedding_readiness_sends_auth_headers(monkeypatch):
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200

    class FakeAsyncClient:
        def __init__(self, *, timeout: float):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def post(self, url: str, *, json: dict, headers: dict[str, str]):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr("router.readiness.httpx.AsyncClient", FakeAsyncClient)
    settings = RouterSettings(
        routes={"fast": RouteSpec(description="low risk", utterances=["x"])},
        embedding_url="http://embedding/v1/embeddings",
        embedding_model="embed-model",
        embedding_api_key="sk-embed",
        embedding_headers={"X-Provider": "local"},
        readiness_timeout=0.5,
    )

    status = await ReadinessChecker(settings).check_embedding()

    assert status == ComponentStatus(ok=True, detail="status=200")
    assert captured["url"] == "http://embedding/v1/embeddings"
    assert captured["json"] == {"model": "embed-model", "input": ["ping"]}
    assert captured["headers"] == {
        "X-Provider": "local",
        "Authorization": "Bearer sk-embed",
    }
