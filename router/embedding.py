from __future__ import annotations

from typing import Protocol

import httpx


class EmbeddingClient(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text."""


class OpenAIEmbeddingClient:
    def __init__(self, url: str, model: str, timeout: float = 20.0):
        self.url = url
        self.model = model
        self.timeout = timeout

    async def embed(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                self.url,
                json={"model": self.model, "input": texts},
            )
            response.raise_for_status()
            payload = response.json()
        return [item["embedding"] for item in payload["data"]]

