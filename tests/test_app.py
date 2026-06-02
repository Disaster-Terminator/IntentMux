from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
import json
import logging
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from router.app import (
    create_app,
    main,
    stream_with_context,
    usage_from_response_content,
)
from router.config import RouteSpec, RouterSettings
from router.readiness import ComponentStatus, ReadinessReport
from router.routing import Router, RoutingDecision


class FakeRouter:
    def __init__(self, decision: RoutingDecision):
        self.decision = decision
        self.requests: list[dict[str, Any]] = []
        self.format_signals: list[dict[str, Any] | None] = []

    async def decide(
        self,
        request_json: dict[str, Any],
        format_signals: dict[str, Any] | None = None,
    ) -> RoutingDecision:
        self.requests.append(request_json)
        self.format_signals.append(format_signals)
        return self.decision


class FailingEmbeddingClient:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("embedding unavailable")


class FakeDecisionEmbeddingClient:
    def __init__(self, vectors: dict[str, list[float]], fail: bool = False):
        self.vectors = vectors
        self.fail = fail

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if self.fail:
            raise RuntimeError("embedding unavailable")
        return [self.vectors[text] for text in texts]


def decision_router_settings() -> RouterSettings:
    return RouterSettings(
        route_model="intentmux",
        fallback_route_id="lite",
        threshold=0.5,
        margin=0.05,
        routes={
            "lite": RouteSpec(
                target_model="lite-upstream",
                description="lite",
                utterances=["翻译", "总结"],
            ),
            "deep": RouteSpec(
                target_model="deep-upstream",
                description="deep",
                utterances=["线上", "PR审查"],
            ),
        },
        hard_rules=[{"route_id": "deep", "keywords": ["线上", "PR"]}],
    )


def test_usage_from_response_content_extracts_safe_openai_usage_only():
    assert usage_from_response_content(
        b'{"usage":{"prompt_tokens":3,"completion_tokens":4,"total_tokens":7,"text":"no"}}'
    ) == {
        "prompt_tokens": 3,
        "completion_tokens": 4,
        "total_tokens": 7,
    }
    assert usage_from_response_content(b'{"usage":{"prompt_tokens":-1}}') is None
    assert usage_from_response_content(b"not json") is None


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
            content=(
                b'{"id":"chatcmpl-test","choices":[],'
                b'"usage":{"prompt_tokens":11,"completion_tokens":7,"total_tokens":18}}'
            ),
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


class NoUpstreamProxy:
    def __init__(self):
        self.forward_called = False
        self.stream_called = False

    async def forward_chat(self, payload: dict[str, Any], headers: dict[str, str]):
        self.forward_called = True
        raise AssertionError("/v1/intentmux/decision must not call forward_chat")

    @asynccontextmanager
    async def stream_chat(self, payload: dict[str, Any], headers: dict[str, str]):
        self.stream_called = True
        raise AssertionError("/v1/intentmux/decision must not call stream_chat")
        yield


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


class UpstreamBadRequestProxy(FakeProxy):
    async def forward_chat(
        self, payload: dict[str, Any], headers: dict[str, str]
    ) -> FakeProxyResponse:
        self.payloads.append(payload)
        self.headers.append(headers)
        return FakeProxyResponse(
            status_code=400,
            content=b'{"error":{"message":"bad request"}}',
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
            RoutingDecision(
                "lite-upstream", "test", rewrite=True, source_model="intentmux"
            )
        ),
        proxy=FakeProxy(),
    )

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_models_lists_only_canonical_synthetic_entries_without_targets():
    app = create_app(
        settings=RouterSettings(
            route_model="intentmux",
            fallback_route_id="lite",
            routes={
                "lite": RouteSpec(
                    target_model="local-lite-model",
                    description="lite",
                    utterances=["翻译"],
                ),
                "deep": RouteSpec(
                    target_model="local-deep-model",
                    description="deep",
                    utterances=["代码审查"],
                ),
            },
        ),
        router=FakeRouter(
            RoutingDecision("local-lite-model", "test", rewrite=True, route_id="lite")
        ),
        proxy=FakeProxy(),
    )

    response = TestClient(app).get("/v1/models")

    assert response.status_code == 200
    assert response.json() == {
        "object": "list",
        "data": [
            {"id": "intentmux", "object": "model"},
            {"id": "lite", "object": "model"},
            {"id": "deep", "object": "model"},
        ],
    }
    response_text = response.text
    assert "semantic-router" not in response_text
    assert "auto" not in response_text
    assert "local-lite-model" not in response_text
    assert "local-deep-model" not in response_text


def test_models_requires_inbound_api_key_when_configured():
    app = create_app(
        settings=RouterSettings(
            route_model="intentmux",
            fallback_route_id="lite",
            inbound_api_key="sk-intentmux",
            routes={
                "lite": RouteSpec(
                    target_model="lite-upstream", description="lite", utterances=["hi"]
                )
            },
        ),
        router=FakeRouter(
            RoutingDecision("lite-upstream", "test", rewrite=True, route_id="lite")
        ),
        proxy=FakeProxy(),
    )
    client = TestClient(app)

    assert client.get("/v1/models").status_code == 401
    assert (
        client.get(
            "/v1/models",
            headers={"Authorization": "Bearer sk-intentmux"},
        ).status_code
        == 200
    )


def test_intentmux_decision_endpoint_alias_matches_legacy_contract():
    proxy = NoUpstreamProxy()
    router = Router(
        decision_router_settings(),
        FakeDecisionEmbeddingClient({}),
    )
    app = create_app(router=router, proxy=proxy)

    response = TestClient(app).post(
        "/v1/intentmux/decision",
        json={
            "model": "intentmux",
            "messages": [{"role": "user", "content": "这个线上 bug 为什么偶发"}],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_model"] == "intentmux"
    assert body["route_id"] == "deep"
    assert body["target_model"] == "deep-upstream"
    assert body["policy_id"] == "hard_rule"


def test_main_disables_uvicorn_access_log_by_default(monkeypatch):
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        "router.app.load_settings",
        lambda: RouterSettings(
            route_model="intentmux",
            default_route="lite-upstream",
            routes={
                "lite-upstream": RouteSpec(
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


def test_main_logs_runtime_config_diagnostics(tmp_path: Path, monkeypatch, caplog):
    runtime_home = tmp_path / "intentmux-home"
    config_path = runtime_home / "config" / "routes.yaml"
    audit_dir = runtime_home / "logs" / "routes"
    monkeypatch.setattr(
        "router.app.load_settings",
        lambda: RouterSettings(
            config_path=str(config_path),
            config_source="ROUTER_CONFIG",
            runtime_home=str(runtime_home),
            runtime_config_exists=True,
            audit_log_enabled=True,
            audit_log_dir=str(audit_dir),
            access_log=False,
            routes={
                "lite": RouteSpec(
                    description="cheap",
                    utterances=["hello"],
                )
            },
        ),
    )
    monkeypatch.setattr("router.app.uvicorn.run", lambda *args, **kwargs: None)

    with caplog.at_level("INFO", logger="intentmux"):
        main()

    assert "config_source=ROUTER_CONFIG" in caplog.text
    assert f"config_path={config_path}" in caplog.text
    assert f"runtime_home={runtime_home}" in caplog.text
    assert "runtime_config_exists=true" in caplog.text
    assert "audit_log_enabled=true" in caplog.text
    assert "access_log=false" in caplog.text


def test_chat_completion_rewrites_smart_router_before_forwarding():
    proxy = FakeProxy()
    app = create_app(
        router=FakeRouter(
            RoutingDecision(
                "deep-upstream",
                "hard_rule:线上",
                rewrite=True,
                source_model="intentmux",
                score=None,
            )
        ),
        proxy=proxy,
    )

    response = TestClient(app).post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer litellm-test"},
        json={
            "model": "intentmux",
            "messages": [{"role": "user", "content": "这个线上 bug 为什么偶发"}],
        },
    )

    assert response.status_code == 200
    assert proxy.payloads[0]["model"] == "deep-upstream"
    assert proxy.headers[0]["authorization"] == "Bearer litellm-test"
    assert response.headers["x-router-target-model"] == "deep-upstream"
    assert response.headers["x-router-reason"] == "hard_rule:%E7%BA%BF%E4%B8%8A"
    assert "x-router-route-id" not in response.headers
    assert "x-router-policy-id" not in response.headers


def test_cloud_chat_completion_hides_target_model_header_by_default():
    proxy = FakeProxy()
    app = create_app(
        settings=RouterSettings(
            route_model="intentmux",
            fallback_route_id="lite",
            inbound_api_key="sk-intentmux",
            cloud_mode=True,
            expose_target_model_header=False,
            routes={
                "lite": RouteSpec(
                    target_model="lite-upstream",
                    description="lite",
                    utterances=["hi"],
                ),
                "deep": RouteSpec(
                    target_model="deep-upstream",
                    description="deep",
                    utterances=["debug"],
                ),
            },
        ),
        router=FakeRouter(
            RoutingDecision(
                "deep-upstream",
                "semantic",
                rewrite=True,
                route_id="deep",
                source_model="intentmux",
            )
        ),
        proxy=proxy,
    )

    response = TestClient(app).post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer sk-intentmux"},
        json={
            "model": "intentmux",
            "messages": [{"role": "user", "content": "debug this"}],
        },
    )

    assert response.status_code == 200
    assert "x-router-target-model" not in response.headers
    assert response.headers["x-router-route-id"] == "deep"
    assert response.headers["x-router-reason"] == "semantic"


def test_chat_completion_keeps_passthrough_model():
    proxy = FakeProxy()
    app = create_app(
        router=FakeRouter(
            RoutingDecision(
                "deepseek-v4-pro",
                "passthrough",
                rewrite=False,
                source_model="deepseek-v4-pro",
                policy_id="passthrough",
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
    assert "x-router-route-id" not in response.headers
    assert response.headers["x-router-policy-id"] == "passthrough"


def test_decision_endpoint_hard_rule_returns_contract_without_forwarding():
    proxy = NoUpstreamProxy()
    router = Router(
        decision_router_settings(),
        FakeDecisionEmbeddingClient({}),
    )
    app = create_app(router=router, proxy=proxy)

    response = TestClient(app).post(
        "/v1/intentmux/decision",
        json={
            "model": "intentmux",
            "messages": [{"role": "user", "content": "这个线上 bug 为什么偶发"}],
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "source_model": "intentmux",
        "route_id": "deep",
        "target_model": "deep-upstream",
        "policy_id": "hard_rule",
        "reason": "hard_rule:线上",
        "rewrite": True,
        "score": None,
        "second_score": None,
        "score_margin": None,
        "threshold": None,
        "margin": None,
        "top_route_id": None,
        "second_route_id": None,
        "match_source": None,
        "match_index": None,
        "match_text_sha256": None,
        "match_score": None,
        "match_provenance": None,
        "route_vector_source": None,
        "route_vector_load_ms": None,
        "query_embedding_ms": None,
    }
    assert proxy.forward_called is False
    assert proxy.stream_called is False


def test_decision_endpoint_explicit_route_override_returns_explicit_policy():
    proxy = NoUpstreamProxy()
    app = create_app(
        router=Router(decision_router_settings(), FakeDecisionEmbeddingClient({})),
        proxy=proxy,
    )

    response = TestClient(app).post(
        "/v1/intentmux/decision",
        json={
            "model": "intentmux",
            "messages": [{"role": "user", "content": "无关文本"}],
            "metadata": {"route_id": "deep"},
        },
    )

    assert response.status_code == 200
    assert response.json()["route_id"] == "deep"
    assert response.json()["target_model"] == "deep-upstream"
    assert response.json()["policy_id"] == "explicit"
    assert proxy.forward_called is False
    assert proxy.stream_called is False


def test_decision_endpoint_requires_inbound_api_key_when_configured():
    app = create_app(
        settings=RouterSettings(
            route_model="intentmux",
            fallback_route_id="lite",
            inbound_api_key="sk-intentmux",
            routes={
                "lite": RouteSpec(
                    target_model="lite-upstream", description="lite", utterances=["hi"]
                )
            },
        ),
        router=FakeRouter(
            RoutingDecision("lite-upstream", "test", rewrite=True, route_id="lite")
        ),
        proxy=FakeProxy(),
    )
    client = TestClient(app)

    missing = client.post("/v1/intentmux/decision", json={"model": "intentmux"})
    wrong = client.post(
        "/v1/intentmux/decision",
        headers={"Authorization": "Bearer wrong"},
        json={"model": "intentmux"},
    )
    ok = client.post(
        "/v1/intentmux/decision",
        headers={"Authorization": "Bearer sk-intentmux"},
        json={"model": "intentmux"},
    )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert ok.status_code == 200


def test_chat_completion_requires_inbound_api_key_when_configured():
    app = create_app(
        settings=RouterSettings(
            route_model="intentmux",
            fallback_route_id="lite",
            inbound_api_key="sk-intentmux",
            routes={
                "lite": RouteSpec(
                    target_model="lite-upstream", description="lite", utterances=["hi"]
                )
            },
        ),
        router=FakeRouter(
            RoutingDecision("lite-upstream", "test", rewrite=True, route_id="lite")
        ),
        proxy=FakeProxy(),
    )
    client = TestClient(app)

    missing = client.post(
        "/v1/chat/completions",
        json={"model": "intentmux", "messages": [{"role": "user", "content": "hi"}]},
    )
    wrong = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer wrong"},
        json={"model": "intentmux", "messages": [{"role": "user", "content": "hi"}]},
    )
    ok = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer sk-intentmux"},
        json={"model": "intentmux", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert ok.status_code == 200


def test_chat_completion_accepts_inbound_api_key_rotation_slots():
    app = create_app(
        settings=RouterSettings(
            route_model="intentmux",
            fallback_route_id="lite",
            inbound_api_key="sk-current",
            inbound_api_keys=["sk-current", "sk-next"],
            routes={
                "lite": RouteSpec(
                    target_model="lite-upstream", description="lite", utterances=["hi"]
                )
            },
        ),
        router=FakeRouter(
            RoutingDecision("lite-upstream", "test", rewrite=True, route_id="lite")
        ),
        proxy=FakeProxy(),
    )
    client = TestClient(app)

    next_key = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer sk-next"},
        json={"model": "intentmux", "messages": [{"role": "user", "content": "hi"}]},
    )
    wrong = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer wrong"},
        json={"model": "intentmux", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert next_key.status_code == 200
    assert wrong.status_code == 401


def test_chat_completion_does_not_write_prompt_review_log_by_default(tmp_path: Path):
    prompt_dir = tmp_path / "prompts"
    app = create_app(
        settings=RouterSettings(
            route_model="intentmux",
            fallback_route_id="lite",
            prompt_log_dir=str(prompt_dir),
            routes={
                "lite": RouteSpec(
                    target_model="lite-upstream", description="lite", utterances=["hi"]
                )
            },
        ),
        router=FakeRouter(
            RoutingDecision("lite-upstream", "test", rewrite=True, route_id="lite")
        ),
        proxy=FakeProxy(),
    )

    response = TestClient(app).post(
        "/v1/chat/completions",
        json={
            "model": "intentmux",
            "messages": [{"role": "user", "content": "raw local prompt"}],
        },
    )

    assert response.status_code == 200
    assert not prompt_dir.exists()


def test_chat_completion_writes_raw_local_prompt_review_log(tmp_path: Path):
    prompt_dir = tmp_path / "prompts"
    app = create_app(
        settings=RouterSettings(
            route_model="intentmux",
            fallback_route_id="lite",
            prompt_log_mode="raw_local",
            prompt_log_dir=str(prompt_dir),
            routes={
                "lite": RouteSpec(
                    target_model="lite-upstream", description="lite", utterances=["hi"]
                )
            },
        ),
        router=FakeRouter(
            RoutingDecision("lite-upstream", "test", rewrite=True, route_id="lite")
        ),
        proxy=FakeProxy(),
    )

    response = TestClient(app).post(
        "/v1/chat/completions",
        headers={"x-request-id": "req-prompt"},
        json={
            "model": "intentmux",
            "messages": [{"role": "user", "content": "请分析回滚方案"}],
        },
    )

    assert response.status_code == 200
    log_lines = (
        list(prompt_dir.glob("*.jsonl"))[0].read_text(encoding="utf-8").splitlines()
    )
    record = json.loads(log_lines[0])
    assert record["event"] == "prompt_review"
    assert record["request_id"] == "req-prompt"
    assert record["mode"] == "raw_local"
    assert record["latest_user_text"] == "请分析回滚方案"
    assert record["route_id"] == "lite"
    assert record["target_model"] == "lite-upstream"


def test_chat_completion_redacted_prompt_review_log_masks_credentials(tmp_path: Path):
    prompt_dir = tmp_path / "prompts"
    app = create_app(
        settings=RouterSettings(
            route_model="intentmux",
            fallback_route_id="lite",
            prompt_log_mode="redacted",
            prompt_log_dir=str(prompt_dir),
            routes={
                "lite": RouteSpec(
                    target_model="lite-upstream", description="lite", utterances=["hi"]
                )
            },
        ),
        router=FakeRouter(
            RoutingDecision("lite-upstream", "test", rewrite=True, route_id="lite")
        ),
        proxy=FakeProxy(),
    )

    response = TestClient(app).post(
        "/v1/chat/completions",
        headers={"x-request-id": "req-redacted"},
        json={
            "model": "intentmux",
            "messages": [{"role": "user", "content": "use Bearer abcdefghijklmnop"}],
        },
    )

    assert response.status_code == 200
    log_lines = (
        list(prompt_dir.glob("*.jsonl"))[0].read_text(encoding="utf-8").splitlines()
    )
    record = json.loads(log_lines[0])
    assert record["latest_user_text"] == "use [REDACTED]"


def test_health_and_local_ready_do_not_require_inbound_api_key():
    app = create_app(
        settings=RouterSettings(
            route_model="intentmux",
            fallback_route_id="lite",
            inbound_api_key="sk-intentmux",
            routes={
                "lite": RouteSpec(
                    target_model="lite-upstream", description="lite", utterances=["hi"]
                )
            },
        ),
        router=FakeRouter(
            RoutingDecision("lite-upstream", "test", rewrite=True, route_id="lite")
        ),
        proxy=FakeProxy(),
        readiness_checker=FakeReadinessChecker(
            ReadinessReport(
                ready=True,
                components={
                    "router": ComponentStatus(ok=True),
                    "litellm": ComponentStatus(ok=True),
                    "embedding": ComponentStatus(ok=True),
                },
            )
        ),
    )
    client = TestClient(app)

    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200


def test_cloud_ready_requires_inbound_api_key():
    app = create_app(
        settings=RouterSettings(
            route_model="intentmux",
            fallback_route_id="lite",
            inbound_api_key="sk-intentmux",
            cloud_mode=True,
            routes={
                "lite": RouteSpec(
                    target_model="lite-upstream", description="lite", utterances=["hi"]
                )
            },
        ),
        router=FakeRouter(
            RoutingDecision("lite-upstream", "test", rewrite=True, route_id="lite")
        ),
        proxy=FakeProxy(),
        readiness_checker=FakeReadinessChecker(
            ReadinessReport(
                ready=True,
                components={
                    "router": ComponentStatus(ok=True),
                    "litellm": ComponentStatus(ok=True),
                    "embedding": ComponentStatus(ok=True),
                },
            )
        ),
    )
    client = TestClient(app)

    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 401
    assert (
        client.get(
            "/ready",
            headers={"Authorization": "Bearer sk-intentmux"},
        ).status_code
        == 200
    )


def test_cloud_runtime_status_requires_auth_and_redacts_private_fields():
    app = create_app(
        settings=RouterSettings(
            route_model="intentmux",
            entry_model_aliases=["sonnet"],
            route_id_aliases={"cheap": "lite"},
            fallback_route_id="cheap",
            threshold=0.42,
            margin=0.07,
            cloud_mode=True,
            inbound_api_key="sk-intentmux",
            config_path="/data/config/routes.yaml",
            config_source="ROUTER_CONFIG",
            config_sha256="a" * 64,
            route_bank_sha256="b" * 64,
            runtime_home="/data",
            runtime_config_exists=True,
            route_bank_loaded=True,
            routes={
                "lite": RouteSpec(
                    target_model="private-lite-target",
                    description="lite",
                    utterances=["hi", "summarize"],
                ),
                "deep": RouteSpec(
                    target_model="private-deep-target",
                    description="deep",
                    utterances=["debug"],
                ),
            },
            hard_rules=[{"route_id": "deep", "keywords": ["secret-keyword"]}],
        ),
        router=FakeRouter(
            RoutingDecision("private-lite-target", "test", rewrite=True, route_id="lite")
        ),
        proxy=FakeProxy(),
    )
    client = TestClient(app)

    assert client.get("/v1/intentmux/status").status_code == 401

    response = client.get(
        "/v1/intentmux/status",
        headers={"Authorization": "Bearer sk-intentmux"},
    )

    assert response.status_code == 200
    payload = response.json()
    serialized = json.dumps(payload)
    assert payload["config"]["config_source"] == "ROUTER_CONFIG"
    assert payload["config"]["config_sha256"] == "a" * 64
    assert payload["routing"]["fallback_route_id"] == "lite"
    assert payload["routing"]["entry_model_aliases"] == ["sonnet"]
    assert payload["routing"]["route_id_aliases"] == {"cheap": "lite"}
    assert payload["routes"]["lite"]["utterance_count"] == 2
    assert payload["routes"]["lite"]["target_model_configured"] is True
    assert "target_model" not in payload["routes"]["lite"]
    assert "target_model_sha256" in payload["routes"]["lite"]
    assert payload["hard_rules"][0]["keyword_count"] == 1
    assert "keywords" not in payload["hard_rules"][0]
    assert "keyword_sha256s" in payload["hard_rules"][0]
    assert "/data" not in serialized
    assert "private-lite-target" not in serialized
    assert "secret-keyword" not in serialized


def test_local_runtime_status_includes_paths_and_targets_for_debugging():
    app = create_app(
        settings=RouterSettings(
            route_model="intentmux",
            fallback_route_id="lite",
            config_path="config/routes.yaml",
            runtime_home=".intentmux-home",
            routes={
                "lite": RouteSpec(
                    target_model="local-lite-target",
                    description="lite",
                    utterances=["hi"],
                )
            },
            hard_rules=[{"route_id": "lite", "keywords": ["local"]}],
        ),
        router=FakeRouter(
            RoutingDecision("local-lite-target", "test", rewrite=True, route_id="lite")
        ),
        proxy=FakeProxy(),
    )

    payload = TestClient(app).get("/v1/intentmux/status").json()

    assert payload["config"]["config_path"] == "config/routes.yaml"
    assert payload["config"]["runtime_home"] == ".intentmux-home"
    assert payload["routes"]["lite"]["target_model"] == "local-lite-target"
    assert payload["hard_rules"][0]["keywords"] == ["local"]


def test_local_diagnostic_endpoints_require_auth_when_inbound_key_configured():
    app = create_app(
        settings=RouterSettings(
            route_model="intentmux",
            fallback_route_id="lite",
            inbound_api_key="sk-intentmux",
            routes={
                "lite": RouteSpec(
                    target_model="lite-upstream",
                    description="lite",
                    utterances=["hi"],
                )
            },
        ),
        router=FakeRouter(
            RoutingDecision("lite-upstream", "test", rewrite=True, route_id="lite")
        ),
        proxy=FakeProxy(),
    )
    client = TestClient(app)

    assert client.get("/v1/intentmux/status").status_code == 401
    assert client.get("/v1/intentmux/counters").status_code == 401
    assert (
        client.get(
            "/v1/intentmux/status",
            headers={"Authorization": "Bearer sk-intentmux"},
        ).status_code
        == 200
    )
    assert (
        client.get(
            "/v1/intentmux/counters",
            headers={"Authorization": "Bearer sk-intentmux"},
        ).status_code
        == 200
    )


def test_route_counters_record_success_and_error_without_request_ids():
    client = TestClient(
        create_app(
            settings=RouterSettings(
                route_model="intentmux",
                fallback_route_id="lite",
                routes={
                    "lite": RouteSpec(
                        target_model="lite-upstream",
                        description="lite",
                        utterances=["hi"],
                    )
                },
            ),
            router=FakeRouter(
                RoutingDecision(
                    "lite-upstream",
                    "test",
                    rewrite=True,
                    route_id="lite",
                    policy_id="accepted",
                    route_vector_source="cache",
                )
            ),
            proxy=FakeProxy(),
        )
    )

    response = client.post(
        "/v1/chat/completions",
        headers={"x-request-id": "req-success"},
        json={"model": "intentmux", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    counters = client.get("/v1/intentmux/counters").json()
    assert counters["total"] == 1
    assert counters["by_event"] == {"route_complete": 1}
    assert counters["by_route_id"] == {"lite": 1}
    assert counters["by_policy_id"] == {"accepted": 1}
    assert counters["by_outcome"] == {"success": 1}
    assert counters["by_route_vector_source"] == {"cache": 1}
    assert "req-success" not in json.dumps(counters)


def test_route_counters_record_error_class():
    client = TestClient(
        create_app(
            settings=RouterSettings(
                route_model="intentmux",
                fallback_route_id="lite",
                routes={
                    "lite": RouteSpec(
                        target_model="lite-upstream",
                        description="lite",
                        utterances=["hi"],
                    )
                },
            ),
            router=FakeRouter(
                RoutingDecision(
                    "lite-upstream",
                    "test",
                    rewrite=True,
                    route_id="lite",
                    policy_id="accepted",
                )
            ),
            proxy=UpstreamStatusProxy(),
        )
    )

    response = client.post(
        "/v1/chat/completions",
        json={"model": "intentmux", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 502
    counters = client.get("/v1/intentmux/counters").json()
    assert counters["total"] == 1
    assert counters["by_event"] == {"route_error": 1}
    assert counters["by_outcome"] == {"upstream_non_200": 1}
    assert counters["by_error_class"] == {"upstream_server_error": 1}


def test_decision_endpoint_low_confidence_uses_fallback_route_id():
    proxy = NoUpstreamProxy()
    vectors = {
        "翻译": [1.0, 0.0],
        "总结": [1.0, 0.0],
        "线上": [0.0, 1.0],
        "PR审查": [0.0, 1.0],
        "天气怎么样": [0.3, 0.3],
    }
    app = create_app(
        router=Router(decision_router_settings(), FakeDecisionEmbeddingClient(vectors)),
        proxy=proxy,
    )

    response = TestClient(app).post(
        "/v1/intentmux/decision",
        json={
            "model": "intentmux",
            "messages": [{"role": "user", "content": "天气怎么样"}],
        },
    )

    assert response.status_code == 200
    assert response.json()["route_id"] == "lite"
    assert response.json()["target_model"] == "lite-upstream"
    assert response.json()["policy_id"] == "low_confidence"
    assert proxy.forward_called is False
    assert proxy.stream_called is False


def test_decision_endpoint_agent_tool_signal_routes_deep_before_low_confidence():
    proxy = NoUpstreamProxy()
    app = create_app(
        router=Router(decision_router_settings(), FakeDecisionEmbeddingClient({})),
        proxy=proxy,
    )
    messages = [{"role": "user", "content": "x" * 13000}]
    messages.extend({"role": "assistant", "content": "ok"} for _ in range(5))

    response = TestClient(app).post(
        "/v1/intentmux/decision",
        json={
            "model": "intentmux",
            "messages": messages,
            "tools": [{"type": "function", "function": {"name": "read_file"}}],
        },
    )

    assert response.status_code == 200
    assert response.json()["route_id"] == "deep"
    assert response.json()["target_model"] == "deep-upstream"
    assert response.json()["policy_id"] == "agent_signal"
    assert proxy.forward_called is False
    assert proxy.stream_called is False


def test_decision_endpoint_agent_long_context_signal_routes_deep():
    proxy = NoUpstreamProxy()
    app = create_app(
        router=Router(decision_router_settings(), FakeDecisionEmbeddingClient({})),
        proxy=proxy,
    )
    messages = [{"role": "user", "content": "x" * 13000}]
    messages.extend({"role": "assistant", "content": "ok"} for _ in range(5))

    response = TestClient(app).post(
        "/v1/intentmux/decision",
        json={"model": "intentmux", "messages": messages},
    )

    assert response.status_code == 200
    assert response.json()["route_id"] == "deep"
    assert response.json()["target_model"] == "deep-upstream"
    assert response.json()["policy_id"] == "agent_signal"
    assert proxy.forward_called is False
    assert proxy.stream_called is False


def test_decision_endpoint_embedding_error_uses_fallback_route_id_and_policy():
    proxy = NoUpstreamProxy()
    app = create_app(
        router=Router(
            decision_router_settings(), FakeDecisionEmbeddingClient({}, fail=True)
        ),
        proxy=proxy,
    )

    response = TestClient(app).post(
        "/v1/intentmux/decision",
        json={
            "model": "intentmux",
            "messages": [{"role": "user", "content": "解释一下这个概念"}],
        },
    )

    assert response.status_code == 200
    assert response.json()["route_id"] == "lite"
    assert response.json()["target_model"] == "lite-upstream"
    assert response.json()["policy_id"] == "embedding_error"
    assert proxy.forward_called is False
    assert proxy.stream_called is False


def test_decision_endpoint_passthrough_keeps_model_without_inventing_route_id_and_stable_shape():
    proxy = NoUpstreamProxy()
    app = create_app(
        router=Router(decision_router_settings(), FakeDecisionEmbeddingClient({})),
        proxy=proxy,
    )

    response = TestClient(app).post(
        "/v1/intentmux/decision",
        json={
            "model": "deepseek-v4-pro",
            "messages": [{"role": "user", "content": "just answer directly"}],
            "prompt": "sensitive prompt should never be mirrored",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "source_model": "deepseek-v4-pro",
        "route_id": None,
        "target_model": "deepseek-v4-pro",
        "policy_id": "passthrough",
        "reason": "passthrough",
        "rewrite": False,
        "score": None,
        "second_score": None,
        "score_margin": None,
        "threshold": None,
        "margin": None,
        "top_route_id": None,
        "second_route_id": None,
        "match_source": None,
        "match_index": None,
        "match_text_sha256": None,
        "match_score": None,
        "match_provenance": None,
        "route_vector_source": None,
        "route_vector_load_ms": None,
        "query_embedding_ms": None,
    }
    assert set(response.json()) == {
        "source_model",
        "route_id",
        "target_model",
        "policy_id",
        "reason",
        "rewrite",
        "score",
        "second_score",
        "score_margin",
        "threshold",
        "margin",
        "top_route_id",
        "second_route_id",
        "match_source",
        "match_index",
        "match_text_sha256",
        "match_score",
        "match_provenance",
        "route_vector_source",
        "route_vector_load_ms",
        "query_embedding_ms",
    }
    assert "prompt" not in response.text
    assert proxy.forward_called is False
    assert proxy.stream_called is False


def test_decision_endpoint_returns_400_for_invalid_json_without_leaking_input():
    proxy = NoUpstreamProxy()
    app = create_app(
        router=FakeRouter(
            RoutingDecision("lite-upstream", "passthrough", rewrite=False)
        ),
        proxy=proxy,
    )
    client = TestClient(app)

    response = client.post(
        "/v1/intentmux/decision",
        data='{"model":"intentmux","messages":[{"role":"user","content":"secret"',
        headers={
            "content-type": "application/json",
            "authorization": "Bearer super-secret-token",
        },
    )

    assert response.status_code == 400
    assert response.json() == {"error": {"message": "Invalid JSON request body"}}
    assert "secret" not in response.text
    assert "super-secret-token" not in response.text
    assert proxy.forward_called is False
    assert proxy.stream_called is False


def test_chat_completion_returns_400_for_invalid_json_without_leaking_input():
    proxy = NoUpstreamProxy()
    app = create_app(
        router=FakeRouter(
            RoutingDecision("lite-upstream", "passthrough", rewrite=False)
        ),
        proxy=proxy,
    )
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        data='{"model":"intentmux","messages":[{"role":"user","content":"secret"',
        headers={
            "content-type": "application/json",
            "authorization": "Bearer super-secret-token",
        },
    )

    assert response.status_code == 400
    assert response.json() == {"error": {"message": "Invalid JSON request body"}}
    assert "secret" not in response.text
    assert "super-secret-token" not in response.text
    assert proxy.forward_called is False
    assert proxy.stream_called is False


def test_chat_completion_returns_400_for_non_object_payload_without_leaking_input():
    proxy = NoUpstreamProxy()
    app = create_app(
        router=FakeRouter(
            RoutingDecision("lite-upstream", "passthrough", rewrite=False)
        ),
        proxy=proxy,
    )
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        headers={"authorization": "Bearer super-secret-token"},
        json=["super", "sensitive", {"prompt": "do not leak"}],
    )

    assert response.status_code == 400
    assert response.json() == {"error": {"message": "JSON body must be an object"}}
    assert "sensitive" not in response.text
    assert "super-secret-token" not in response.text
    assert proxy.forward_called is False
    assert proxy.stream_called is False


def test_decision_endpoint_returns_400_for_non_object_payload_without_leaking_input():
    proxy = NoUpstreamProxy()
    app = create_app(
        router=FakeRouter(
            RoutingDecision("lite-upstream", "passthrough", rewrite=False)
        ),
        proxy=proxy,
    )
    client = TestClient(app)

    response = client.post(
        "/v1/intentmux/decision",
        headers={"authorization": "Bearer super-secret-token"},
        json=["super", "sensitive", {"prompt": "do not leak"}],
    )

    assert response.status_code == 400
    assert response.json() == {"error": {"message": "JSON body must be an object"}}
    assert "sensitive" not in response.text
    assert "super-secret-token" not in response.text
    assert proxy.forward_called is False
    assert proxy.stream_called is False


def test_decision_endpoint_missing_model_and_messages_preserves_router_semantics():
    proxy = NoUpstreamProxy()
    router = FakeRouter(
        RoutingDecision(
            target_model="lite-upstream",
            reason="passthrough",
            rewrite=False,
            source_model=None,
        )
    )
    app = create_app(router=router, proxy=proxy)
    client = TestClient(app)

    response = client.post("/v1/intentmux/decision", json={"metadata": {"k": "v"}})

    assert response.status_code == 200
    assert router.requests == [{"metadata": {"k": "v"}}]
    assert response.json() == {
        "source_model": None,
        "route_id": None,
        "target_model": "lite-upstream",
        "policy_id": None,
        "reason": "passthrough",
        "rewrite": False,
        "score": None,
        "second_score": None,
        "score_margin": None,
        "threshold": None,
        "margin": None,
        "top_route_id": None,
        "second_route_id": None,
        "match_source": None,
        "match_index": None,
        "match_text_sha256": None,
        "match_score": None,
        "match_provenance": None,
        "route_vector_source": None,
        "route_vector_load_ms": None,
        "query_embedding_ms": None,
    }
    assert proxy.forward_called is False
    assert proxy.stream_called is False


def test_streaming_chat_completion_uses_stream_proxy():
    proxy = FakeProxy()
    app = create_app(
        router=FakeRouter(
            RoutingDecision(
                "deep-upstream",
                "hard_rule:线上",
                rewrite=True,
                route_id="deep",
                policy_id="hard_rule",
                source_model="intentmux",
            )
        ),
        proxy=proxy,
    )

    with TestClient(app).stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "intentmux",
            "stream": True,
            "messages": [{"role": "user", "content": "这个线上 bug 为什么偶发"}],
        },
    ) as response:
        body = response.read()

    assert response.status_code == 200
    assert proxy.payloads[0]["model"] == "deep-upstream"
    assert proxy.payloads[0]["stream"] is True
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache, no-transform"
    assert response.headers["x-accel-buffering"] == "no"
    assert response.headers["x-router-target-model"] == "deep-upstream"
    assert response.headers["x-router-route-id"] == "deep"
    assert response.headers["x-router-policy-id"] == "hard_rule"
    assert body == b"data: first\n\ndata: [DONE]\n\n"


def test_chat_completion_emits_structured_log_without_sensitive_payload(caplog):
    proxy = FakeProxy()
    app = create_app(
        router=FakeRouter(
            RoutingDecision(
                "deep-upstream",
                "hard_rule:线上",
                rewrite=True,
                route_id="deep",
                policy_id="hard_rule",
                source_model="intentmux",
            )
        ),
        proxy=proxy,
    )

    with caplog.at_level(logging.INFO, logger="intentmux"):
        response = TestClient(app).post(
            "/v1/chat/completions",
            headers={
                "Authorization": "Bearer litellm-test",
                "x-request-id": "external-request-1",
            },
            json={
                "model": "intentmux",
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
            "config_sha256": route_logs[0]["config_sha256"],
            "config_source": route_logs[0]["config_source"],
            "completion_tokens": 7,
            "decision_ms": route_logs[0]["decision_ms"],
            "duration_ms": route_logs[0]["duration_ms"],
            "event": "route_complete",
            "format_signals": {
                "approx_input_chars": 27,
                "assistant_message_count": 0,
                "function_count": 0,
                "functions_present": False,
                "message_count": 1,
                "multimodal_content": False,
                "response_format_present": False,
                "system_message_count": 0,
                "tool_call_count": 0,
                "tool_choice_present": False,
                "tool_count": 0,
                "tool_history": False,
                "tool_message_count": 0,
                "tools_present": False,
                "user_message_count": 1,
            },
            "ok": True,
            "outcome": "success",
            "policy_id": "hard_rule",
            "prompt_tokens": 11,
            "reason": "hard_rule:线上",
            "request_id": "external-request-1",
            "request_id_source": "x-request-id",
            "rewrite": True,
            "route_bank_sha256": route_logs[0]["route_bank_sha256"],
            "route_id": "deep",
            "score": None,
            "second_score": None,
            "source_model": "intentmux",
            "status": 200,
            "stream": False,
            "target_model": "deep-upstream",
            "total_tokens": 18,
            "ts": route_logs[0]["ts"],
            "upstream_ms": route_logs[0]["upstream_ms"],
            "upstream_status": 200,
        }
    ]
    assert route_logs[0]["decision_ms"] >= 0
    assert route_logs[0]["upstream_ms"] >= 0
    assert route_logs[0]["config_source"]
    assert len(route_logs[0]["config_sha256"]) == 64
    assert len(route_logs[0]["route_bank_sha256"]) == 64
    assert "config_path" not in route_logs[0]
    assert "runtime_home" not in route_logs[0]
    serialized = "\n".join(record.message for record in caplog.records)
    assert "敏感 prompt" not in serialized
    assert "Bearer litellm-test" not in serialized


def test_chat_completion_audit_log_includes_format_signals_without_content(caplog):
    proxy = FakeProxy()
    router = FakeRouter(
        RoutingDecision("lite-upstream", "test", rewrite=True, route_id="lite")
    )
    app = create_app(
        router=router,
        proxy=proxy,
    )

    with caplog.at_level(logging.INFO, logger="intentmux"):
        response = TestClient(app).post(
            "/v1/chat/completions",
            json={
                "model": "intentmux",
                "messages": [
                    {"role": "user", "content": "private edit request"},
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{"id": "call-1", "type": "function"}],
                    },
                ],
                "tools": [{"type": "function", "function": {"name": "edit_file"}}],
            },
        )

    assert response.status_code == 200
    records = [json.loads(record.message) for record in caplog.records]
    route_log = next(
        record for record in records if record["event"] == "route_complete"
    )
    assert route_log["format_signals"] == {
        "approx_input_chars": 20,
        "assistant_message_count": 1,
        "function_count": 0,
        "functions_present": False,
        "message_count": 2,
        "multimodal_content": False,
        "response_format_present": False,
        "system_message_count": 0,
        "tool_call_count": 1,
        "tool_choice_present": False,
        "tool_count": 1,
        "tool_history": True,
        "tool_message_count": 0,
        "tools_present": True,
        "user_message_count": 1,
    }
    assert router.format_signals == [route_log["format_signals"]]
    assert "private edit request" not in json.dumps(route_log, ensure_ascii=False)


def test_chat_completion_writes_redacted_audit_log(tmp_path):
    audit_dir = tmp_path / "logs" / "routes"
    settings = RouterSettings(
        route_model="intentmux",
        fallback_route_id="lite",
        routes={
            "lite": RouteSpec(
                target_model="lite-upstream",
                description="lite",
                utterances=["hello"],
            )
        },
        audit_log_enabled=True,
        audit_log_dir=str(audit_dir),
    )
    app = create_app(
        settings=settings,
        router=FakeRouter(
            RoutingDecision(
                "lite-upstream",
                "embedding",
                rewrite=True,
                route_id="lite",
                policy_id="embedding",
                source_model="intentmux",
                score=0.7,
                second_score=0.2,
                route_vector_source="disk_cache",
                route_vector_load_ms=1.25,
                query_embedding_ms=12.5,
            )
        ),
        proxy=FakeProxy(),
    )

    response = TestClient(app).post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer litellm-test"},
        json={
            "model": "intentmux",
            "metadata": {"semantic_router_request_id": "audit-request-1"},
            "messages": [{"role": "user", "content": "敏感 prompt"}],
        },
    )

    assert response.status_code == 200
    audit_files = list(audit_dir.glob("*.jsonl"))
    assert len(audit_files) == 1
    records = [json.loads(line) for line in audit_files[0].read_text().splitlines()]
    assert records == [
        {
            "decision_ms": records[0]["decision_ms"],
            "duration_ms": records[0]["duration_ms"],
            "event": "route_complete",
            "format_signals": {
                "approx_input_chars": 9,
                "assistant_message_count": 0,
                "function_count": 0,
                "functions_present": False,
                "message_count": 1,
                "multimodal_content": False,
                "response_format_present": False,
                "system_message_count": 0,
                "tool_call_count": 0,
                "tool_choice_present": False,
                "tool_count": 0,
                "tool_history": False,
                "tool_message_count": 0,
                "tools_present": False,
                "user_message_count": 1,
            },
            "ok": True,
            "outcome": "success",
            "policy_id": "embedding",
            "completion_tokens": 7,
            "prompt_tokens": 11,
            "reason": "embedding",
            "request_id": "audit-request-1",
            "request_id_source": "metadata.semantic_router_request_id",
            "rewrite": True,
            "query_embedding_ms": 12.5,
            "route_vector_load_ms": 1.25,
            "route_vector_source": "disk_cache",
            "route_id": "lite",
            "score": 0.7,
            "second_score": 0.2,
            "source_model": "intentmux",
            "status": 200,
            "stream": False,
            "target_model": "lite-upstream",
            "total_tokens": 18,
            "ts": records[0]["ts"],
            "upstream_ms": records[0]["upstream_ms"],
            "upstream_status": 200,
        }
    ]
    assert records[0]["decision_ms"] >= 0
    assert records[0]["upstream_ms"] >= 0
    serialized = audit_files[0].read_text()
    assert "敏感 prompt" not in serialized
    assert "Bearer litellm-test" not in serialized


def test_chat_completion_marks_upstream_4xx_as_unhealthy_without_gateway_rewrite(
    caplog,
):
    app = create_app(
        router=FakeRouter(
            RoutingDecision(
                "lite-upstream",
                "low_confidence",
                rewrite=True,
                route_id="lite",
                policy_id="low_confidence",
                source_model="intentmux",
                score=0.36,
                second_score=0.19,
            )
        ),
        proxy=UpstreamBadRequestProxy(),
    )

    with caplog.at_level(logging.INFO, logger="intentmux"):
        response = TestClient(app, raise_server_exceptions=False).post(
            "/v1/chat/completions",
            json={
                "model": "intentmux",
                "metadata": {"semantic_router_request_id": "bad-request-1"},
                "messages": [{"role": "user", "content": "敏感 prompt"}],
            },
        )

    assert response.status_code == 400
    records = [json.loads(record.message) for record in caplog.records]
    route_logs = [record for record in records if record["event"] == "route_complete"]
    assert len(route_logs) == 1
    assert route_logs[0]["request_id"] == "bad-request-1"
    assert route_logs[0]["upstream_status"] == 400
    assert route_logs[0]["ok"] is False
    assert route_logs[0]["outcome"] == "upstream_non_200"


def test_chat_completion_uses_metadata_request_id_when_header_is_not_forwarded(caplog):
    proxy = FakeProxy()
    app = create_app(
        router=FakeRouter(
            RoutingDecision(
                "deep-upstream",
                "hard_rule:线上",
                rewrite=True,
                source_model="intentmux",
            )
        ),
        proxy=proxy,
    )

    with caplog.at_level(logging.INFO, logger="intentmux"):
        response = TestClient(app).post(
            "/v1/chat/completions",
            json={
                "model": "intentmux",
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
    assert "metadata" not in proxy.payloads[0]


def test_chat_completion_strips_router_private_metadata_before_forwarding():
    proxy = FakeProxy()
    app = create_app(
        router=FakeRouter(
            RoutingDecision(
                "deep-upstream",
                "metadata.route_id",
                rewrite=True,
                source_model="intentmux",
                route_id="deep",
                policy_id="explicit_override",
            )
        ),
        proxy=proxy,
    )

    response = TestClient(app).post(
        "/v1/chat/completions",
        json={
            "model": "intentmux",
            "metadata": {
                "route_id": "deep",
                "route": "lite",
                "target_route": "deep",
                "semantic_router_request_id": "metadata-request-2",
                "tenant": "kept",
            },
            "messages": [{"role": "user", "content": "这个线上 bug 为什么偶发"}],
        },
    )

    assert response.status_code == 200
    assert proxy.payloads[0]["metadata"] == {"tenant": "kept"}


def test_chat_completion_does_not_use_user_field_as_request_id(caplog):
    proxy = FakeProxy()
    app = create_app(
        router=FakeRouter(
            RoutingDecision(
                "deep-upstream",
                "hard_rule:线上",
                rewrite=True,
                source_model="intentmux",
            )
        ),
        proxy=proxy,
    )

    with caplog.at_level(logging.INFO, logger="intentmux"):
        response = TestClient(app).post(
            "/v1/chat/completions",
            json={
                "model": "intentmux",
                "user": "user-request-1",
                "messages": [{"role": "user", "content": "这个线上 bug 为什么偶发"}],
            },
        )

    assert response.headers["x-router-request-id"] != "user-request-1"
    assert proxy.headers[0]["x-request-id"] != "user-request-1"
    records = [json.loads(record.message) for record in caplog.records]
    route_logs = [record for record in records if record["event"] == "route_complete"]
    assert route_logs[0]["request_id"] == response.headers["x-router-request-id"]
    assert route_logs[0]["request_id_source"] == "generated"


def test_chat_completion_rejects_unsafe_request_id_header(caplog):
    proxy = FakeProxy()
    app = create_app(
        router=FakeRouter(
            RoutingDecision(
                "deep-upstream",
                "hard_rule:线上",
                rewrite=True,
                source_model="intentmux",
            )
        ),
        proxy=proxy,
    )

    with caplog.at_level(logging.INFO, logger="intentmux"):
        response = TestClient(app).post(
            "/v1/chat/completions",
            headers={"x-request-id": "Bearer sk-secret-token"},
            json={
                "model": "intentmux",
                "messages": [{"role": "user", "content": "这个线上 bug 为什么偶发"}],
            },
        )

    assert response.status_code == 200
    assert response.headers["x-router-request-id"] != "Bearer sk-secret-token"
    assert proxy.headers[0]["x-request-id"] == response.headers["x-router-request-id"]
    records = [json.loads(record.message) for record in caplog.records]
    route_logs = [record for record in records if record["event"] == "route_complete"]
    assert route_logs[0]["request_id"] == response.headers["x-router-request-id"]
    assert route_logs[0]["request_id_source"] == "generated"
    serialized = "\n".join(record.message for record in caplog.records)
    assert "sk-secret-token" not in serialized


def test_chat_completion_uses_traceparent_when_request_id_headers_are_absent(caplog):
    proxy = FakeProxy()
    app = create_app(
        router=FakeRouter(
            RoutingDecision(
                "deep-upstream",
                "hard_rule:线上",
                rewrite=True,
                source_model="intentmux",
            )
        ),
        proxy=proxy,
    )

    trace_id = "0123456789abcdef0123456789abcdef"
    with caplog.at_level(logging.INFO, logger="intentmux"):
        response = TestClient(app).post(
            "/v1/chat/completions",
            headers={"traceparent": f"00-{trace_id}-0123456789abcdef-01"},
            json={
                "model": "intentmux",
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
        route_model="intentmux",
        default_route="lite-upstream",
        routes={
            "lite-upstream": RouteSpec(
                description="low risk",
                utterances=["解释一下这个概念"],
            ),
            "deep-upstream": RouteSpec(
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

    with caplog.at_level(logging.INFO, logger="intentmux"):
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "intentmux",
                "metadata": {"semantic_router_request_id": "embedding-degraded-1"},
                "messages": [{"role": "user", "content": "敏感 prompt"}],
            },
        )

    assert response.status_code == 200
    assert proxy.payloads[0]["model"] == "lite-upstream"
    assert response.headers["x-router-target-model"] == "lite-upstream"
    records = [json.loads(record.message) for record in caplog.records]
    route_complete = [
        record for record in records if record["event"] == "route_complete"
    ]
    route_errors = [record for record in records if record["event"] == "route_error"]
    assert route_errors == []
    assert len(route_complete) == 1
    assert route_complete[0]["request_id"] == "embedding-degraded-1"
    assert route_complete[0]["target_model"] == "lite-upstream"
    assert route_complete[0]["reason"] == "embedding_error"
    serialized = "\n".join(record.message for record in caplog.records)
    assert "敏感 prompt" not in serialized


def test_chat_completion_logs_structured_route_error_without_sensitive_payload(caplog):
    app = create_app(
        router=FakeRouter(
            RoutingDecision(
                "lite-upstream",
                "embedding",
                rewrite=True,
                source_model="intentmux",
                score=0.7,
                second_score=0.2,
            )
        ),
        proxy=FailingProxy(),
    )

    with caplog.at_level(logging.INFO, logger="intentmux"):
        response = TestClient(app, raise_server_exceptions=False).post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer litellm-test"},
            json={
                "model": "intentmux",
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
    assert route_logs[0]["target_model"] == "lite-upstream"
    assert route_logs[0]["error_class"] == "upstream_timeout"
    assert route_logs[0]["error_type"] == "TimeoutError"
    assert route_logs[0]["status"] is None
    serialized = "\n".join(record.message for record in caplog.records)
    assert "敏感 prompt" not in serialized
    assert "Bearer litellm-test" not in serialized


def test_chat_completion_maps_upstream_5xx_to_redacted_route_error(caplog):
    app = create_app(
        router=FakeRouter(
            RoutingDecision(
                "lite-upstream",
                "embedding",
                rewrite=True,
                source_model="intentmux",
                score=0.7,
                second_score=0.2,
            )
        ),
        proxy=UpstreamStatusProxy(),
    )

    with caplog.at_level(logging.INFO, logger="intentmux"):
        response = TestClient(app, raise_server_exceptions=False).post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer litellm-test"},
            json={
                "model": "intentmux",
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
    route_complete = [
        record for record in records if record["event"] == "route_complete"
    ]
    route_errors = [record for record in records if record["event"] == "route_error"]
    assert route_complete == []
    assert len(route_errors) == 1
    assert route_errors[0]["request_id"] == "status-error-request-1"
    assert route_errors[0]["target_model"] == "lite-upstream"
    assert route_errors[0]["error_class"] == "upstream_server_error"
    assert route_errors[0]["error_type"] == "UpstreamStatusError"
    assert route_errors[0]["status"] == 503
    assert route_errors[0]["upstream_status"] == 503
    serialized = "\n".join(record.message for record in caplog.records)
    assert "敏感 prompt" not in serialized
    assert "Bearer litellm-test" not in serialized
    assert "upstream leaked sensitive body" not in response.text
    assert "upstream leaked sensitive body" not in serialized


def test_streaming_chat_completion_returns_gateway_error_when_upstream_disconnects(
    caplog,
):
    app = create_app(
        router=FakeRouter(
            RoutingDecision(
                "deep-upstream",
                "hard_rule:PR",
                rewrite=True,
                source_model="intentmux",
            )
        ),
        proxy=FailingStreamProxy(),
    )

    with caplog.at_level(logging.INFO, logger="intentmux"):
        response = TestClient(app, raise_server_exceptions=False).post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer litellm-test"},
            json={
                "model": "intentmux",
                "stream": True,
                "metadata": {"semantic_router_request_id": "stream-error-request-1"},
                "messages": [{"role": "user", "content": "敏感 prompt"}],
            },
        )

    assert response.status_code == 502
    assert response.headers["x-router-request-id"] == "stream-error-request-1"
    assert response.headers["x-router-target-model"] == "deep-upstream"
    assert response.headers["x-router-reason"] == "hard_rule:PR"
    assert "x-router-route-id" not in response.headers
    assert "x-router-policy-id" not in response.headers
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
                "deep-upstream",
                "hard_rule:PR",
                rewrite=True,
                source_model="intentmux",
            )
        ),
        proxy=proxy,
    )

    with caplog.at_level(logging.INFO, logger="intentmux"):
        response = TestClient(app, raise_server_exceptions=False).post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer litellm-test"},
            json={
                "model": "intentmux",
                "stream": True,
                "metadata": {
                    "semantic_router_request_id": "stream-status-error-request-1"
                },
                "messages": [{"role": "user", "content": "敏感 prompt"}],
            },
        )

    assert response.status_code == 502
    assert response.headers["x-router-request-id"] == "stream-status-error-request-1"
    assert response.headers["x-router-target-model"] == "deep-upstream"
    assert response.headers["x-router-reason"] == "hard_rule:PR"
    assert "x-router-route-id" not in response.headers
    assert "x-router-policy-id" not in response.headers
    assert response.json()["error"]["type"] == "UpstreamStatusError"
    assert proxy.stream_context_closed is True
    records = [json.loads(record.message) for record in caplog.records]
    route_complete = [
        record for record in records if record["event"] == "route_complete"
    ]
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
                "deep-upstream",
                "hard_rule:线上",
                rewrite=True,
                source_model="intentmux",
            )
        ),
        proxy=proxy,
    )

    with caplog.at_level(logging.INFO, logger="intentmux"):
        with TestClient(app).stream(
            "POST",
            "/v1/chat/completions",
            headers={"x-request-id": "stream-request-1"},
            json={
                "model": "intentmux",
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
    assert route_logs[0]["target_model"] == "deep-upstream"
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

    with caplog.at_level(logging.INFO, logger="intentmux"):
        stream = stream_with_context(
            chunks(),
            stream_context,
            request_id="stream-request-closed",
            request_id_source="x-request-id",
            decision=RoutingDecision(
                "deep-upstream",
                "hard_rule:线上",
                rewrite=True,
                source_model="intentmux",
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


async def test_streaming_chat_completion_logs_route_error_when_body_iteration_fails(
    caplog,
):
    class StreamContext:
        def __init__(self):
            self.exit_calls = 0

        async def __aexit__(self, exc_type, exc, traceback):
            self.exit_calls += 1

    async def chunks():
        yield b"data: first\n\n"
        raise TimeoutError("upstream body failed")

    stream_context = StreamContext()

    with caplog.at_level(logging.INFO, logger="intentmux"):
        stream = stream_with_context(
            chunks(),
            stream_context,
            request_id="stream-body-error",
            request_id_source="x-request-id",
            decision=RoutingDecision(
                "deep-upstream",
                "hard_rule:PR",
                rewrite=True,
                source_model="intentmux",
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
    route_complete = [
        record for record in records if record["event"] == "route_complete"
    ]
    route_errors = [record for record in records if record["event"] == "route_error"]
    assert stream_context.exit_calls == 1
    assert route_complete == []
    assert len(route_errors) == 1
    assert route_errors[0]["request_id"] == "stream-body-error"
    assert route_errors[0]["request_id_source"] == "x-request-id"
    assert route_errors[0]["stream"] is True
    assert route_errors[0]["error_type"] == "TimeoutError"
