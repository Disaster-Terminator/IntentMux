from __future__ import annotations

import pytest

from router.embedding import (
    OpenAIEmbeddingClient,
    batched,
    build_embedding_headers,
    clip_embedding_input,
)


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


@pytest.mark.asyncio
async def test_openai_embedding_client_batches_large_inputs(monkeypatch):
    captured_inputs: list[list[str]] = []

    class FakeResponse:
        def __init__(self, batch: list[str]):
            self.batch = batch

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "data": [
                    {"embedding": [float(index)]}
                    for index, _text in enumerate(self.batch)
                ]
            }

    class FakeAsyncClient:
        def __init__(self, *, timeout: float):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def post(self, url: str, *, json: dict, headers: dict[str, str]):
            batch = list(json["input"])
            captured_inputs.append(batch)
            return FakeResponse(batch)

    monkeypatch.setattr("router.embedding.httpx.AsyncClient", FakeAsyncClient)

    client = OpenAIEmbeddingClient(
        "http://embedding/v1/embeddings",
        "embed-model",
        batch_size=2,
    )

    vectors = await client.embed(["a", "b", "c", "d", "e"])

    assert captured_inputs == [["a", "b"], ["c", "d"], ["e"]]
    assert vectors == [[0.0], [1.0], [0.0], [1.0], [0.0]]


def test_batched_rejects_non_positive_batch_size():
    with pytest.raises(ValueError, match="batch_size must be positive"):
        batched(["a"], 0)


def test_clip_embedding_input_preserves_short_text():
    assert clip_embedding_input("short", 10) == "short"
    assert clip_embedding_input("short", None) == "short"


def test_clip_embedding_input_keeps_head_and_tail():
    assert clip_embedding_input("0123456789abcdef", 10) == "01234bcdef"


@pytest.mark.asyncio
async def test_openai_embedding_client_clips_inputs(monkeypatch):
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"data": [{"embedding": [0.1]}]}

    class FakeAsyncClient:
        def __init__(self, *, timeout: float):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def post(self, url: str, *, json: dict, headers: dict[str, str]):
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr("router.embedding.httpx.AsyncClient", FakeAsyncClient)

    client = OpenAIEmbeddingClient(
        "http://embedding/v1/embeddings",
        "embed-model",
        input_max_chars=8,
    )

    vectors = await client.embed(["0123456789abcdef"])

    assert vectors == [[0.1]]
    assert captured["json"] == {"model": "embed-model", "input": ["0123cdef"]}


def test_openai_embedding_client_rejects_non_positive_input_max_chars():
    with pytest.raises(ValueError, match="input_max_chars must be positive"):
        OpenAIEmbeddingClient(
            "http://embedding/v1/embeddings",
            "embed-model",
            input_max_chars=0,
        )
