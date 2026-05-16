from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import socket
import threading
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.testclient import TestClient
import uvicorn

from router.app import create_app
from router.config import RouteSpec, RouterSettings
from router.proxy import LiteLLMProxy
from router.routing import Router


class FakeEmbeddingClient:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise AssertionError("explicit model routes must not call embeddings")


class FakeOpenAIUpstream:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.authorization_headers: list[str | None] = []
        self.app = FastAPI()

        @self.app.post("/v1/chat/completions")
        async def chat_completions(request: Request):
            payload = await request.json()
            self.requests.append(payload)
            self.authorization_headers.append(request.headers.get("authorization"))
            if payload.get("stream") is True:
                async def chunks():
                    yield b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
                    yield b"data: [DONE]\n\n"

                return StreamingResponse(chunks(), media_type="text/event-stream")
            return JSONResponse(
                {
                    "id": "chatcmpl-test",
                    "object": "chat.completion",
                    "model": payload["model"],
                    "choices": [],
                }
            )


def test_nonstream_completion_passes_through_common_fields_to_fake_upstream():
    upstream = FakeOpenAIUpstream()
    with run_uvicorn(upstream.app) as base_url:
        client = TestClient(intentmux_app(base_url))

        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "lite",
                "messages": [{"role": "user", "content": "hello"}],
                "temperature": 0.2,
                "top_p": 0.9,
                "max_tokens": 8,
                "custom_field": "kept",
            },
        )

    assert response.status_code == 200
    assert response.json()["model"] == "local-lite-model"
    assert upstream.requests == [
        {
            "model": "local-lite-model",
            "messages": [{"role": "user", "content": "hello"}],
            "temperature": 0.2,
            "top_p": 0.9,
            "max_tokens": 8,
            "custom_field": "kept",
        }
    ]
    assert upstream.authorization_headers == ["Bearer sk-upstream"]


def test_stream_completion_preserves_upstream_sse_chunks():
    upstream = FakeOpenAIUpstream()
    with run_uvicorn(upstream.app) as base_url:
        client = TestClient(intentmux_app(base_url))

        with client.stream(
            "POST",
            "/v1/chat/completions",
            json={
                "model": "deep",
                "stream": True,
                "messages": [{"role": "user", "content": "review this"}],
            },
        ) as response:
            body = response.read()

    assert response.status_code == 200
    assert b'data: {"choices":[{"delta":{"content":"hi"}}]}' in body
    assert b"data: [DONE]" in body
    assert upstream.requests == [
        {
            "model": "local-deep-model",
            "stream": True,
            "messages": [{"role": "user", "content": "review this"}],
        }
    ]


def intentmux_app(upstream_base_url: str) -> FastAPI:
    settings = RouterSettings(
        route_model="auto",
        fallback_route_id="lite",
        routes={
            "lite": RouteSpec(
                target_model="local-lite-model",
                description="lite",
                utterances=["hello"],
            ),
            "deep": RouteSpec(
                target_model="local-deep-model",
                description="deep",
                utterances=["review"],
            ),
        },
    )
    return create_app(
        settings=settings,
        router=Router(settings, FakeEmbeddingClient()),
        proxy=LiteLLMProxy(upstream_base_url, api_key="sk-upstream"),
    )


@contextmanager
def run_uvicorn(app: FastAPI) -> Iterator[str]:
    port = free_tcp_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError("fake upstream failed to start")
        time.sleep(0.01)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
