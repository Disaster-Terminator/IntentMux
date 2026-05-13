from __future__ import annotations

from typing import Protocol

import httpx


class EmbeddingClient(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text."""


class OpenAIEmbeddingClient:
    def __init__(
        self,
        url: str,
        model: str,
        timeout: float = 20.0,
        api_key: str | None = None,
        headers: dict[str, str] | None = None,
    ):
        self.url = url
        self.model = model
        self.timeout = timeout
        self.api_key = api_key
        self.headers = dict(headers or {})

    async def embed(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                self.url,
                json={"model": self.model, "input": texts},
                headers=build_embedding_headers(
                    api_key=self.api_key,
                    custom_headers=self.headers,
                ),
            )
            response.raise_for_status()
            payload = response.json()
        return [item["embedding"] for item in payload["data"]]


def build_embedding_headers(
    *,
    api_key: str | None = None,
    custom_headers: dict[str, str] | None = None,
) -> dict[str, str]:
    headers = dict(custom_headers or {})
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers
