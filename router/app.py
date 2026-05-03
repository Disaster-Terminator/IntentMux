from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import Response, StreamingResponse

from router.config import RouterSettings, load_settings
from router.embedding import OpenAIEmbeddingClient
from router.proxy import LiteLLMProxy
from router.routing import Router


logger = logging.getLogger("gateway_semantic_router")


def create_app(
    settings: RouterSettings | None = None,
    router: Router | None = None,
    proxy: LiteLLMProxy | None = None,
) -> FastAPI:
    if settings is None:
        settings = load_settings()
    if router is None:
        router = Router(
            settings,
            OpenAIEmbeddingClient(settings.embedding_url, settings.embedding_model),
        )
    if proxy is None:
        proxy = LiteLLMProxy(settings.litellm_base_url)

    app = FastAPI(title="Gateway Semantic Router")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> Response:
        payload: dict[str, Any] = await request.json()
        decision = await router.decide(payload)
        forwarded_payload = dict(payload)
        forwarded_payload["model"] = decision.target_model
        logger.info(
            "route source=%s target=%s reason=%s score=%s second_score=%s",
            decision.source_model,
            decision.target_model,
            decision.reason,
            decision.score,
            decision.second_score,
        )
        router_headers = route_headers(decision.target_model, decision.reason)
        if forwarded_payload.get("stream") is True:
            stream_context = proxy.stream_chat(forwarded_payload, dict(request.headers))
            upstream = await stream_context.__aenter__()
            headers = dict(upstream.headers)
            headers.update(router_headers)
            return StreamingResponse(
                stream_with_context(upstream.content, stream_context),
                status_code=upstream.status_code,
                headers=headers,
                media_type=headers.get("content-type", "text/event-stream"),
            )

        upstream = await proxy.forward_chat(forwarded_payload, dict(request.headers))
        headers = dict(upstream.headers)
        headers.update(router_headers)
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=headers,
            media_type=headers.get("content-type"),
        )

    return app


def route_headers(target_model: str, reason: str) -> dict[str, str]:
    return {
        "x-router-target-model": target_model,
        "x-router-reason": quote(reason, safe=":._-"),
    }


async def stream_with_context(body_iterator, stream_context):
    try:
        async for chunk in body_iterator:
            yield chunk
    except BaseException as exc:
        await stream_context.__aexit__(type(exc), exc, exc.__traceback__)
        raise
    else:
        await stream_context.__aexit__(None, None, None)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = load_settings()
    uvicorn.run(
        create_app(settings=settings),
        host=settings.listen_host,
        port=settings.listen_port,
    )


if __name__ == "__main__":
    main()
