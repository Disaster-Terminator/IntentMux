from __future__ import annotations

import logging
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import Response, StreamingResponse

from router.config import RouterSettings, load_settings
from router.embedding import OpenAIEmbeddingClient
from router.observability import (
    configure_logging,
    log_route_complete,
    log_route_error,
    now_ms,
    request_id_from_request,
    route_headers,
)
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
        proxy = LiteLLMProxy(settings.litellm_base_url, timeout=settings.litellm_timeout)

    app = FastAPI(title="Gateway Semantic Router")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> Response:
        started_ms = now_ms()
        request_headers = dict(request.headers)
        payload: dict[str, Any] = await request.json()
        request_id = request_id_from_request(request_headers, payload)
        decision = await router.decide(payload)
        forwarded_payload = dict(payload)
        forwarded_payload["model"] = decision.target_model
        router_headers = route_headers(decision.target_model, decision.reason, request_id)
        if forwarded_payload.get("stream") is True:
            stream_context = proxy.stream_chat(forwarded_payload, request_headers)
            try:
                upstream = await stream_context.__aenter__()
            except Exception as exc:
                log_route_error(
                    logger,
                    request_id=request_id,
                    decision=decision,
                    stream=True,
                    error=exc,
                    started_ms=started_ms,
                )
                raise
            headers = dict(upstream.headers)
            headers.update(router_headers)
            return StreamingResponse(
                stream_with_context(
                    upstream.content,
                    stream_context,
                    request_id=request_id,
                    decision=decision,
                    upstream_status=upstream.status_code,
                    started_ms=started_ms,
                ),
                status_code=upstream.status_code,
                headers=headers,
                media_type=headers.get("content-type", "text/event-stream"),
            )

        try:
            upstream = await proxy.forward_chat(forwarded_payload, request_headers)
        except Exception as exc:
            log_route_error(
                logger,
                request_id=request_id,
                decision=decision,
                stream=False,
                error=exc,
                started_ms=started_ms,
            )
            raise
        headers = dict(upstream.headers)
        headers.update(router_headers)
        log_route_complete(
            logger,
            request_id=request_id,
            decision=decision,
            stream=False,
            upstream_status=upstream.status_code,
            started_ms=started_ms,
        )
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=headers,
            media_type=headers.get("content-type"),
        )

    return app


async def stream_with_context(
    body_iterator,
    stream_context,
    *,
    request_id: str,
    decision,
    upstream_status: int,
    started_ms: float,
):
    exc_info = (None, None, None)
    try:
        async for chunk in body_iterator:
            yield chunk
    except BaseException as exc:
        exc_info = (type(exc), exc, exc.__traceback__)
        raise
    finally:
        await stream_context.__aexit__(*exc_info)
        log_route_complete(
            logger,
            request_id=request_id,
            decision=decision,
            stream=True,
            upstream_status=upstream_status,
            started_ms=started_ms,
        )


def main() -> None:
    configure_logging()
    settings = load_settings()
    uvicorn.run(
        create_app(settings=settings),
        host=settings.listen_host,
        port=settings.listen_port,
    )


if __name__ == "__main__":
    main()
