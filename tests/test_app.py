from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
import json
import logging
from typing import Any

from fastapi.testclient import TestClient

from router.app import create_app, main, stream_with_context
from router.config import RouteSpec, RouterSettings
from router.readiness import ComponentStatus, ReadinessReport
from router.routing import Router, RoutingDecision


class FakeRouter:
    def __init__(self, decision: RoutingDecision):
        self.decision = decision
        self.requests: list[dict[str, Any]] = []

    async def decide(self, request_json: dict[str, Any]) -> RoutingDecision:
        self.requests.append(request_json)
        return self.decision


class FailingEmbeddingClient:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("embedding unavailable")


@dataclass
class FakeReadinessChecker:
    report: ReadinessReport

    async def check(self) -> ReadinessReport:
        return self.report


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


class FailingProxy(FakeProxy):
    async def forward_chat(self, payload: dict[str, Any], headers: dict[str, str]):
        self.payloads.append(payload)
        self.headers.append(headers)
        raise TimeoutError("upstream timed out")


class FailingStreamProxy(FakeProxy):
    @asynccontextmanager
    async def stream_chat(self, payload: dict[str, Any], headers: dict[str, str]):
        self.payloads.append(payload)
        self.headers.append(headers)
        raise TimeoutError("upstream stream timed out")
        yield


class UpstreamStatusProxy(FakeProxy):
    async def forward_chat(
        self, payload: dict[str, Any], headers: dict[str, str]
    ) -> FakeProxyResponse:
        self.payloads.append(payload)
        self.headers.append(headers)
        return FakeProxyResponse(
            status_code=503,
            content=b'{"error":{"message":"upstream leaked sensitive body"}}',
            headers={"content-type": "application/json"},
        )


class UpstreamStatusStreamProxy(FakeProxy):
    @asynccontextmanager
    async def stream_chat(self, payload: dict[str, Any], headers: dict[str, str]):
        self.payloads.append(payload)
        self.headers.append(headers)
        self.stream_context_closed = False

        async def chunks():
            yield b'data: {"error":"upstream leaked sensitive stream"}\n\n'

        try:
            yield FakeProxyResponse(
                status_code=503,
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


def test_main_disables_uvicorn_access_log_by_default(monkeypatch):
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        "router.app.load_settings",
        lambda: RouterSettings(
            route_model="semantic-router",
            default_route="cheap-router",
            routes={
                "cheap-router": RouteSpec(
                    description="cheap",
                    utterances=["hello"],
                )
            },
        ),
    )

    def fake_run(app, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("router.app.uvicorn.run", fake_run)

    main()

    assert captured["access_log"] is False


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


def test_decision_endpoint_returns_route_decision_without_forwarding():
    proxy = FakeProxy()
    app = create_app(
        router=FakeRouter(
            RoutingDecision(
                "pro-router",
                "hard_rule:线上",
                rewrite=True,
                source_model="semantic-router",
                score=0.91,
                second_score=0.12,
            )
        ),
        proxy=proxy,
    )

    response = TestClient(app).post(
        "/v1/semantic-router/decision",
        json={
            "model": "semantic-router",
            "messages": [{"role": "user", "content": "这个线上 bug 为什么偶发"}],
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "source_model": "semantic-router",
        "target_model": "pro-router",
        "reason": "hard_rule:线上",
        "rewrite": True,
        "score": 0.91,
        "second_score": 0.12,
    }
    assert proxy.payloads == []


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
            "request_id_source": "x-request-id",
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


def test_chat_completion_uses_metadata_request_id_when_header_is_not_forwarded(caplog):
    proxy = FakeProxy()
    app = create_app(
        router=FakeRouter(
            RoutingDecision(
                "pro-router",
                "hard_rule:线上",
                rewrite=True,
                source_model="semantic-router",
            )
        ),
        proxy=proxy,
    )

    with caplog.at_level(logging.INFO, logger="gateway_semantic_router"):
        response = TestClient(app).post(
            "/v1/chat/completions",
            json={
                "model": "semantic-router",
                "metadata": {
                    "semantic_router_request_id": "metadata-request-1",
                },
                "messages": [{"role": "user", "content": "这个线上 bug 为什么偶发"}],
            },
        )

    assert response.headers["x-router-request-id"] == "metadata-request-1"
    assert proxy.headers[0]["x-request-id"] == "metadata-request-1"
    records = [json.loads(record.message) for record in caplog.records]
    route_logs = [record for record in records if record["event"] == "route_complete"]
    assert route_logs[0]["request_id"] == "metadata-request-1"
    assert route_logs[0]["request_id_source"] == "metadata.semantic_router_request_id"


def test_chat_completion_uses_user_request_id_when_proxy_drops_metadata(caplog):
    proxy = FakeProxy()
    app = create_app(
        router=FakeRouter(
            RoutingDecision(
                "pro-router",
                "hard_rule:线上",
                rewrite=True,
                source_model="semantic-router",
            )
        ),
        proxy=proxy,
    )

    with caplog.at_level(logging.INFO, logger="gateway_semantic_router"):
        response = TestClient(app).post(
            "/v1/chat/completions",
            json={
                "model": "semantic-router",
                "user": "user-request-1",
                "messages": [{"role": "user", "content": "这个线上 bug 为什么偶发"}],
            },
        )

    assert response.headers["x-router-request-id"] == "user-request-1"
    assert proxy.headers[0]["x-request-id"] == "user-request-1"
    records = [json.loads(record.message) for record in caplog.records]
    route_logs = [record for record in records if record["event"] == "route_complete"]
    assert route_logs[0]["request_id"] == "user-request-1"
    assert route_logs[0]["request_id_source"] == "user"


def test_chat_completion_uses_traceparent_when_request_id_headers_are_absent(caplog):
    proxy = FakeProxy()
    app = create_app(
        router=FakeRouter(
            RoutingDecision(
                "pro-router",
                "hard_rule:线上",
                rewrite=True,
                source_model="semantic-router",
            )
        ),
        proxy=proxy,
    )

    trace_id = "0123456789abcdef0123456789abcdef"
    with caplog.at_level(logging.INFO, logger="gateway_semantic_router"):
        response = TestClient(app).post(
            "/v1/chat/completions",
            headers={"traceparent": f"00-{trace_id}-0123456789abcdef-01"},
            json={
                "model": "semantic-router",
                "messages": [{"role": "user", "content": "这个线上 bug 为什么偶发"}],
            },
        )

    assert response.headers["x-router-request-id"] == trace_id
    assert proxy.headers[0]["x-request-id"] == trace_id
    records = [json.loads(record.message) for record in caplog.records]
    route_logs = [record for record in records if record["event"] == "route_complete"]
    assert route_logs[0]["request_id"] == trace_id
    assert route_logs[0]["request_id_source"] == "traceparent"


def test_embedding_degraded_readiness_but_chat_falls_back_to_default_route(caplog):
    settings = RouterSettings(
        route_model="semantic-router",
        default_route="cheap-router",
        routes={
            "cheap-router": RouteSpec(
                description="low risk",
                utterances=["解释一下这个概念"],
            ),
            "pro-router": RouteSpec(
                description="high risk",
                utterances=["分析这个线上 bug"],
            ),
            "free-probe-router": RouteSpec(
                description="probe",
                utterances=["测试免费模型"],
            ),
        },
    )
    proxy = FakeProxy()
    app = create_app(
        settings=settings,
        router=Router(settings, FailingEmbeddingClient()),
        proxy=proxy,
        readiness_checker=FakeReadinessChecker(
            ReadinessReport(
                ready=False,
                components={
                    "router": ComponentStatus(ok=True),
                    "litellm": ComponentStatus(ok=True, detail="status=200"),
                    "embedding": ComponentStatus(ok=False, detail="ConnectError"),
                },
            )
        ),
    )
    client = TestClient(app)

    readiness = client.get("/ready")

    assert readiness.status_code == 503
    assert readiness.json()["ready"] is False
    assert readiness.json()["components"]["embedding"] == {
        "ok": False,
        "detail": "ConnectError",
    }

    with caplog.at_level(logging.INFO, logger="gateway_semantic_router"):
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "semantic-router",
                "metadata": {"semantic_router_request_id": "embedding-degraded-1"},
                "messages": [{"role": "user", "content": "敏感 prompt"}],
            },
        )

    assert response.status_code == 200
    assert proxy.payloads[0]["model"] == "cheap-router"
    assert response.headers["x-router-target-model"] == "cheap-router"
    records = [json.loads(record.message) for record in caplog.records]
    route_complete = [record for record in records if record["event"] == "route_complete"]
    route_errors = [record for record in records if record["event"] == "route_error"]
    assert route_errors == []
    assert len(route_complete) == 1
    assert route_complete[0]["request_id"] == "embedding-degraded-1"
    assert route_complete[0]["target_model"] == "cheap-router"
    assert route_complete[0]["reason"] == "embedding_error"
    serialized = "\n".join(record.message for record in caplog.records)
    assert "敏感 prompt" not in serialized


def test_chat_completion_logs_structured_route_error_without_sensitive_payload(caplog):
    app = create_app(
        router=FakeRouter(
            RoutingDecision(
                "cheap-router",
                "embedding",
                rewrite=True,
                source_model="semantic-router",
                score=0.7,
                second_score=0.2,
            )
        ),
        proxy=FailingProxy(),
    )

    with caplog.at_level(logging.INFO, logger="gateway_semantic_router"):
        response = TestClient(app, raise_server_exceptions=False).post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer litellm-test"},
            json={
                "model": "semantic-router",
                "metadata": {"semantic_router_request_id": "error-request-1"},
                "messages": [{"role": "user", "content": "敏感 prompt"}],
            },
        )

    assert response.status_code == 502
    assert response.json() == {
        "error": {
            "message": "upstream route failed",
            "type": "TimeoutError",
        }
    }
    records = [json.loads(record.message) for record in caplog.records]
    route_logs = [record for record in records if record["event"] == "route_error"]
    assert len(route_logs) == 1
    assert route_logs[0]["request_id"] == "error-request-1"
    assert route_logs[0]["target_model"] == "cheap-router"
    assert route_logs[0]["error_type"] == "TimeoutError"
    serialized = "\n".join(record.message for record in caplog.records)
    assert "敏感 prompt" not in serialized
    assert "Bearer litellm-test" not in serialized


def test_chat_completion_maps_upstream_5xx_to_redacted_route_error(caplog):
    app = create_app(
        router=FakeRouter(
            RoutingDecision(
                "cheap-router",
                "embedding",
                rewrite=True,
                source_model="semantic-router",
                score=0.7,
                second_score=0.2,
            )
        ),
        proxy=UpstreamStatusProxy(),
    )

    with caplog.at_level(logging.INFO, logger="gateway_semantic_router"):
        response = TestClient(app, raise_server_exceptions=False).post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer litellm-test"},
            json={
                "model": "semantic-router",
                "metadata": {"semantic_router_request_id": "status-error-request-1"},
                "messages": [{"role": "user", "content": "敏感 prompt"}],
            },
        )

    assert response.status_code == 502
    assert response.json() == {
        "error": {
            "message": "upstream route failed",
            "type": "UpstreamStatusError",
        }
    }
    records = [json.loads(record.message) for record in caplog.records]
    route_complete = [record for record in records if record["event"] == "route_complete"]
    route_errors = [record for record in records if record["event"] == "route_error"]
    assert route_complete == []
    assert len(route_errors) == 1
    assert route_errors[0]["request_id"] == "status-error-request-1"
    assert route_errors[0]["target_model"] == "cheap-router"
    assert route_errors[0]["error_type"] == "UpstreamStatusError"
    assert route_errors[0]["upstream_status"] == 503
    serialized = "\n".join(record.message for record in caplog.records)
    assert "敏感 prompt" not in serialized
    assert "Bearer litellm-test" not in serialized
    assert "upstream leaked sensitive body" not in response.text
    assert "upstream leaked sensitive body" not in serialized


def test_streaming_chat_completion_returns_gateway_error_when_upstream_disconnects(caplog):
    app = create_app(
        router=FakeRouter(
            RoutingDecision(
                "pro-router",
                "hard_rule:PR",
                rewrite=True,
                source_model="semantic-router",
            )
        ),
        proxy=FailingStreamProxy(),
    )

    with caplog.at_level(logging.INFO, logger="gateway_semantic_router"):
        response = TestClient(app, raise_server_exceptions=False).post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer litellm-test"},
            json={
                "model": "semantic-router",
                "stream": True,
                "metadata": {"semantic_router_request_id": "stream-error-request-1"},
                "messages": [{"role": "user", "content": "敏感 prompt"}],
            },
        )

    assert response.status_code == 502
    assert response.headers["x-router-request-id"] == "stream-error-request-1"
    assert response.headers["x-router-target-model"] == "pro-router"
    assert response.json()["error"]["type"] == "TimeoutError"
    records = [json.loads(record.message) for record in caplog.records]
    route_errors = [record for record in records if record["event"] == "route_error"]
    assert len(route_errors) == 1
    assert route_errors[0]["request_id"] == "stream-error-request-1"
    assert route_errors[0]["stream"] is True
    serialized = "\n".join(record.message for record in caplog.records)
    assert "敏感 prompt" not in serialized
    assert "Bearer litellm-test" not in serialized


def test_streaming_chat_completion_maps_upstream_5xx_to_redacted_route_error(caplog):
    proxy = UpstreamStatusStreamProxy()
    app = create_app(
        router=FakeRouter(
            RoutingDecision(
                "pro-router",
                "hard_rule:PR",
                rewrite=True,
                source_model="semantic-router",
            )
        ),
        proxy=proxy,
    )

    with caplog.at_level(logging.INFO, logger="gateway_semantic_router"):
        response = TestClient(app, raise_server_exceptions=False).post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer litellm-test"},
            json={
                "model": "semantic-router",
                "stream": True,
                "metadata": {"semantic_router_request_id": "stream-status-error-request-1"},
                "messages": [{"role": "user", "content": "敏感 prompt"}],
            },
        )

    assert response.status_code == 502
    assert response.headers["x-router-request-id"] == "stream-status-error-request-1"
    assert response.headers["x-router-target-model"] == "pro-router"
    assert response.json()["error"]["type"] == "UpstreamStatusError"
    assert proxy.stream_context_closed is True
    records = [json.loads(record.message) for record in caplog.records]
    route_complete = [record for record in records if record["event"] == "route_complete"]
    route_errors = [record for record in records if record["event"] == "route_error"]
    assert route_complete == []
    assert len(route_errors) == 1
    assert route_errors[0]["request_id"] == "stream-status-error-request-1"
    assert route_errors[0]["stream"] is True
    assert route_errors[0]["error_type"] == "UpstreamStatusError"
    assert route_errors[0]["upstream_status"] == 503
    serialized = "\n".join(record.message for record in caplog.records)
    assert "敏感 prompt" not in serialized
    assert "Bearer litellm-test" not in serialized
    assert "upstream leaked sensitive stream" not in response.text
    assert "upstream leaked sensitive stream" not in serialized


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
    assert route_logs[0]["request_id_source"] == "x-request-id"
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
            request_id_source="x-request-id",
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


async def test_streaming_chat_completion_logs_route_error_when_body_iteration_fails(caplog):
    class StreamContext:
        def __init__(self):
            self.exit_calls = 0

        async def __aexit__(self, exc_type, exc, traceback):
            self.exit_calls += 1

    async def chunks():
        yield b"data: first\n\n"
        raise TimeoutError("upstream body failed")

    stream_context = StreamContext()

    with caplog.at_level(logging.INFO, logger="gateway_semantic_router"):
        stream = stream_with_context(
            chunks(),
            stream_context,
            request_id="stream-body-error",
            request_id_source="x-request-id",
            decision=RoutingDecision(
                "pro-router",
                "hard_rule:PR",
                rewrite=True,
                source_model="semantic-router",
            ),
            upstream_status=200,
            started_ms=0,
        )
        assert await anext(stream) == b"data: first\n\n"
        try:
            await anext(stream)
        except StopAsyncIteration:
            pass

    records = [json.loads(record.message) for record in caplog.records]
    route_complete = [record for record in records if record["event"] == "route_complete"]
    route_errors = [record for record in records if record["event"] == "route_error"]
    assert stream_context.exit_calls == 1
    assert route_complete == []
    assert len(route_errors) == 1
    assert route_errors[0]["request_id"] == "stream-body-error"
    assert route_errors[0]["request_id_source"] == "x-request-id"
    assert route_errors[0]["stream"] is True
    assert route_errors[0]["error_type"] == "TimeoutError"
