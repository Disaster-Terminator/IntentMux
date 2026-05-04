from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient

from router.app import create_app
from router.readiness import ComponentStatus, ReadinessReport, litellm_status_from_code
from router.routing import RoutingDecision


class FakeRouter:
    async def decide(self, request_json):
        return RoutingDecision("cheap-router", "test", rewrite=True, source_model="semantic-router")


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
