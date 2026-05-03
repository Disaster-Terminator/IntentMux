from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastapi.testclient import TestClient

from router.app import create_app
from router.routing import RoutingDecision


class FakeRouter:
    def __init__(self, decision: RoutingDecision):
        self.decision = decision
        self.requests: list[dict[str, Any]] = []

    async def decide(self, request_json: dict[str, Any]) -> RoutingDecision:
        self.requests.append(request_json)
        return self.decision


@dataclass
class FakeProxyResponse:
    status_code: int
    content: bytes
    headers: dict[str, str]


class FakeProxy:
    def __init__(self):
        self.payloads: list[dict[str, Any]] = []
        self.headers: list[dict[str, str]] = []
        self.stream_context_closed = False

    async def forward_chat(
        self, payload: dict[str, Any], headers: dict[str, str]
    ) -> FakeProxyResponse:
        self.payloads.append(payload)
        self.headers.append(headers)
        return FakeProxyResponse(
            status_code=200,
            content=b'{"id":"chatcmpl-test","choices":[]}',
            headers={"content-type": "application/json"},
        )

    @asynccontextmanager
    async def stream_chat(self, payload: dict[str, Any], headers: dict[str, str]):
        self.payloads.append(payload)
        self.headers.append(headers)
        self.stream_context_closed = False

        async def chunks():
            if self.stream_context_closed:
                raise RuntimeError("stream context closed before body iteration")
            yield b"data: first\n\n"
            yield b"data: [DONE]\n\n"

        try:
            yield FakeProxyResponse(
                status_code=200,
                content=chunks(),
                headers={"content-type": "text/event-stream"},
            )
        finally:
            self.stream_context_closed = True


def test_health_reports_ready():
    app = create_app(
        router=FakeRouter(
            RoutingDecision("cheap-router", "test", rewrite=True, source_model="smart-router")
        ),
        proxy=FakeProxy(),
    )

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_completion_rewrites_smart_router_before_forwarding():
    proxy = FakeProxy()
    app = create_app(
        router=FakeRouter(
            RoutingDecision(
                "pro-router",
                "hard_rule:线上",
                rewrite=True,
                source_model="smart-router",
                score=None,
            )
        ),
        proxy=proxy,
    )

    response = TestClient(app).post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer litellm-test"},
        json={
            "model": "smart-router",
            "messages": [{"role": "user", "content": "这个线上 bug 为什么偶发"}],
        },
    )

    assert response.status_code == 200
    assert proxy.payloads[0]["model"] == "pro-router"
    assert proxy.headers[0]["authorization"] == "Bearer litellm-test"
    assert response.headers["x-router-target-model"] == "pro-router"
    assert response.headers["x-router-reason"] == "hard_rule:%E7%BA%BF%E4%B8%8A"


def test_chat_completion_keeps_passthrough_model():
    proxy = FakeProxy()
    app = create_app(
        router=FakeRouter(
            RoutingDecision(
                "deepseek-v4-pro",
                "passthrough",
                rewrite=False,
                source_model="deepseek-v4-pro",
            )
        ),
        proxy=proxy,
    )

    response = TestClient(app).post(
        "/v1/chat/completions",
        json={
            "model": "deepseek-v4-pro",
            "messages": [{"role": "user", "content": "你好"}],
        },
    )

    assert response.status_code == 200
    assert proxy.payloads[0]["model"] == "deepseek-v4-pro"
    assert response.headers["x-router-target-model"] == "deepseek-v4-pro"
    assert response.headers["x-router-reason"] == "passthrough"


def test_streaming_chat_completion_uses_stream_proxy():
    proxy = FakeProxy()
    app = create_app(
        router=FakeRouter(
            RoutingDecision(
                "pro-router",
                "hard_rule:线上",
                rewrite=True,
                source_model="smart-router",
            )
        ),
        proxy=proxy,
    )

    with TestClient(app).stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "smart-router",
            "stream": True,
            "messages": [{"role": "user", "content": "这个线上 bug 为什么偶发"}],
        },
    ) as response:
        body = response.read()

    assert response.status_code == 200
    assert proxy.payloads[0]["model"] == "pro-router"
    assert proxy.payloads[0]["stream"] is True
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-router-target-model"] == "pro-router"
    assert body == b"data: first\n\ndata: [DONE]\n\n"
