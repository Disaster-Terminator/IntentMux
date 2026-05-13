from __future__ import annotations

import pytest

from router.embedding import OpenAIEmbeddingClient, build_embedding_headers


def test_build_embedding_headers_merges_api_key_and_custom_headers():
    headers = build_embedding_headers(
        api_key="sk-embed",
        custom_headers={"X-Provider": "local"},
    )

    assert headers == {
        "X-Provider": "local",
        "Authorization": "Bearer sk-embed",
    }


@pytest.mark.asyncio
async def test_openai_embedding_client_sends_auth_headers(monkeypatch):
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"data": [{"embedding": [0.1, 0.2]}]}

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

    monkeypatch.setattr("router.embedding.httpx.AsyncClient", FakeAsyncClient)

    client = OpenAIEmbeddingClient(
        "http://embedding/v1/embeddings",
        "embed-model",
        api_key="sk-embed",
        headers={"X-Provider": "local"},
        timeout=3.0,
    )

    vectors = await client.embed(["ping"])

    assert vectors == [[0.1, 0.2]]
    assert captured["url"] == "http://embedding/v1/embeddings"
    assert captured["json"] == {"model": "embed-model", "input": ["ping"]}
    assert captured["headers"] == {
        "X-Provider": "local",
        "Authorization": "Bearer sk-embed",
    }
