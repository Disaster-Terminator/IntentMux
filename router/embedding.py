from __future__ import annotations

from typing import Protocol

import httpx


class EmbeddingClient(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text."""


DEFAULT_EMBEDDING_INPUT_MAX_CHARS = 12_000


class OpenAIEmbeddingClient:
    def __init__(
        self,
        url: str,
        model: str,
        timeout: float = 20.0,
        batch_size: int = 128,
        api_key: str | None = None,
        headers: dict[str, str] | None = None,
        input_max_chars: int | None = DEFAULT_EMBEDDING_INPUT_MAX_CHARS,
    ):
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if input_max_chars is not None and input_max_chars <= 0:
            raise ValueError("input_max_chars must be positive")
        self.url = url
        self.model = model
        self.timeout = timeout
        self.batch_size = batch_size
        self.api_key = api_key
        self.headers = dict(headers or {})
        self.input_max_chars = input_max_chars

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for batch in batched(texts, self.batch_size):
                response = await client.post(
                    self.url,
                    json={
                        "model": self.model,
                        "input": [
                            clip_embedding_input(text, self.input_max_chars)
                            for text in batch
                        ],
                    },
                    headers=build_embedding_headers(
                        api_key=self.api_key,
                        custom_headers=self.headers,
                    ),
                )
                response.raise_for_status()
                payload = response.json()
                vectors.extend(item["embedding"] for item in payload["data"])
        return vectors


def batched(items: list[str], batch_size: int) -> list[list[str]]:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    return [items[index : index + batch_size] for index in range(0, len(items), batch_size)]


def clip_embedding_input(text: str, max_chars: int | None) -> str:
    if max_chars is None or len(text) <= max_chars:
        return text
    head_chars = max_chars // 2
    tail_chars = max_chars - head_chars
    return text[:head_chars] + text[-tail_chars:]


def build_embedding_headers(
    *,
    api_key: str | None = None,
    custom_headers: dict[str, str] | None = None,
) -> dict[str, str]:
    headers = dict(custom_headers or {})
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers
