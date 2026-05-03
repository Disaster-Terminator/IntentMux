from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
import json
import logging
from typing import Any

from fastapi.testclient import TestClient

from router.app import create_app, stream_with_context
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


def test_chat_completion_emits_structured_log_without_sensitive_payload(caplog):
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

    with caplog.at_level(logging.INFO, logger="gateway_semantic_router"):
        response = TestClient(app).post(
            "/v1/chat/completions",
            headers={
                "Authorization": "Bearer litellm-test",
                "x-request-id": "external-request-1",
            },
            json={
                "model": "smart-router",
                "messages": [
                    {
                        "role": "user",
                        "content": "这个线上 bug 为什么偶发，里面有敏感 prompt",
                    }
                ],
            },
        )

    assert response.headers["x-router-request-id"] == "external-request-1"
    records = [json.loads(record.message) for record in caplog.records]
    route_logs = [record for record in records if record["event"] == "route_complete"]
    assert route_logs == [
        {
            "event": "route_complete",
            "request_id": "external-request-1",
            "source_model": "smart-router",
            "target_model": "pro-router",
            "reason": "hard_rule:线上",
            "rewrite": True,
            "stream": False,
            "upstream_status": 200,
            "score": None,
            "second_score": None,
            "duration_ms": route_logs[0]["duration_ms"],
        }
    ]
    serialized = "\n".join(record.message for record in caplog.records)
    assert "敏感 prompt" not in serialized
    assert "Bearer litellm-test" not in serialized


def test_streaming_chat_completion_logs_after_body_iteration(caplog):
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

    with caplog.at_level(logging.INFO, logger="gateway_semantic_router"):
        with TestClient(app).stream(
            "POST",
            "/v1/chat/completions",
            headers={"x-request-id": "stream-request-1"},
            json={
                "model": "smart-router",
                "stream": True,
                "messages": [{"role": "user", "content": "这个线上 bug 为什么偶发"}],
            },
        ) as response:
            response.read()

    assert response.headers["x-router-request-id"] == "stream-request-1"
    records = [json.loads(record.message) for record in caplog.records]
    route_logs = [record for record in records if record["event"] == "route_complete"]
    assert len(route_logs) == 1
    assert route_logs[0]["request_id"] == "stream-request-1"
    assert route_logs[0]["target_model"] == "pro-router"
    assert route_logs[0]["stream"] is True
    assert route_logs[0]["upstream_status"] == 200


async def test_streaming_chat_completion_logs_when_client_closes_early(caplog):
    class StreamContext:
        def __init__(self):
            self.exit_calls = 0

        async def __aexit__(self, exc_type, exc, traceback):
            self.exit_calls += 1

    async def chunks():
        yield b"data: first\n\n"
        yield b"data: [DONE]\n\n"

    stream_context = StreamContext()

    with caplog.at_level(logging.INFO, logger="gateway_semantic_router"):
        stream = stream_with_context(
            chunks(),
            stream_context,
            request_id="stream-request-closed",
            decision=RoutingDecision(
                "pro-router",
                "hard_rule:线上",
                rewrite=True,
                source_model="smart-router",
            ),
            upstream_status=200,
            started_ms=0,
        )
        assert await anext(stream) == b"data: first\n\n"
        await stream.aclose()

    records = [json.loads(record.message) for record in caplog.records]
    route_logs = [record for record in records if record["event"] == "route_complete"]
    assert stream_context.exit_calls == 1
    assert len(route_logs) == 1
    assert route_logs[0]["request_id"] == "stream-request-closed"
    assert route_logs[0]["stream"] is True
