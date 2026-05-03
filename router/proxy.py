from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx


HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}


@dataclass(frozen=True)
class ProxyResponse:
    status_code: int
    content: bytes
    headers: dict[str, str]


class LiteLLMProxy:
    def __init__(self, base_url: str, timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def forward_chat(
        self, payload: dict, headers: dict[str, str]
    ) -> ProxyResponse:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                headers=forwardable_headers(headers),
            )
        return ProxyResponse(
            status_code=response.status_code,
            content=response.content,
            headers=response_headers(response.headers),
        )

    @asynccontextmanager
    async def stream_chat(
        self, payload: dict, headers: dict[str, str]
    ) -> AsyncIterator[ProxyResponse]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                headers=forwardable_headers(headers),
            ) as response:
                yield ProxyResponse(
                    status_code=response.status_code,
                    content=response.aiter_bytes(),
                    headers=response_headers(response.headers),
                )


def forwardable_headers(headers: dict[str, str]) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }


def response_headers(headers: httpx.Headers | dict[str, str]) -> dict[str, str]:
    return {
        key: value
        for key, value in dict(headers).items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }
