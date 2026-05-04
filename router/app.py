from __future__ import annotations

import logging
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from router.config import RouterSettings, load_settings
from router.embedding import OpenAIEmbeddingClient
from router.observability import (
    configure_logging,
    log_route_complete,
    log_route_error,
    now_ms,
    request_identity_from_request,
    route_headers,
)
from router.proxy import LiteLLMProxy
from router.readiness import ReadinessChecker
from router.routing import Router


logger = logging.getLogger("gateway_semantic_router")


def create_app(
    settings: RouterSettings | None = None,
    router: Router | None = None,
    proxy: LiteLLMProxy | None = None,
    readiness_checker: ReadinessChecker | None = None,
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
    if readiness_checker is None:
        readiness_checker = ReadinessChecker(settings)

    app = FastAPI(title="Gateway Semantic Router")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready() -> JSONResponse:
        report = await readiness_checker.check()
        return JSONResponse(
            report.to_dict(),
            status_code=200 if report.ready else 503,
        )

    @app.post("/v1/semantic-router/decision")
    async def route_decision(request: Request) -> dict[str, Any]:
        payload: dict[str, Any] = await request.json()
        decision = await router.decide(payload)
        return {
            "source_model": decision.source_model,
            "target_model": decision.target_model,
            "reason": decision.reason,
            "rewrite": decision.rewrite,
            "score": decision.score,
            "second_score": decision.second_score,
        }

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> Response:
        started_ms = now_ms()
        request_headers = dict(request.headers)
        payload: dict[str, Any] = await request.json()
        request_identity = request_identity_from_request(request_headers, payload)
        request_id = request_identity.value
        request_headers["x-request-id"] = request_id
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
                    request_id_source=request_identity.source,
                    decision=decision,
                    stream=True,
                    error=exc,
                    started_ms=started_ms,
                )
                return upstream_error_response(
                    request_id=request_id,
                    decision=decision,
                    error=exc,
                )
            headers = dict(upstream.headers)
            headers.update(router_headers)
            return StreamingResponse(
                stream_with_context(
                    upstream.content,
                    stream_context,
                    request_id=request_id,
                    request_id_source=request_identity.source,
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
                request_id_source=request_identity.source,
                decision=decision,
                stream=False,
                error=exc,
                started_ms=started_ms,
            )
            return upstream_error_response(
                request_id=request_id,
                decision=decision,
                error=exc,
            )
        headers = dict(upstream.headers)
        headers.update(router_headers)
        log_route_complete(
            logger,
            request_id=request_id,
            request_id_source=request_identity.source,
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
    request_id_source: str,
    decision,
    upstream_status: int,
    started_ms: float,
):
    exc_info = (None, None, None)
    route_error: Exception | None = None
    try:
        async for chunk in body_iterator:
            yield chunk
    except Exception as exc:
        exc_info = (type(exc), exc, exc.__traceback__)
        route_error = exc
        log_route_error(
            logger,
            request_id=request_id,
            request_id_source=request_id_source,
            decision=decision,
            stream=True,
            error=exc,
            started_ms=started_ms,
        )
        return
    except BaseException as exc:
        exc_info = (type(exc), exc, exc.__traceback__)
        raise
    finally:
        await stream_context.__aexit__(*exc_info)
        if route_error is None:
            log_route_complete(
                logger,
                request_id=request_id,
                request_id_source=request_id_source,
                decision=decision,
                stream=True,
                upstream_status=upstream_status,
                started_ms=started_ms,
            )


def upstream_error_response(
    *,
    request_id: str,
    decision,
    error: BaseException,
) -> JSONResponse:
    return JSONResponse(
        {
            "error": {
                "message": "upstream route failed",
                "type": type(error).__name__,
            }
        },
        status_code=502,
        headers=route_headers(decision.target_model, decision.reason, request_id),
    )


def main() -> None:
    configure_logging()
    settings = load_settings()
    uvicorn.run(
        create_app(settings=settings),
        host=settings.listen_host,
        port=settings.listen_port,
        access_log=settings.access_log,
    )


if __name__ == "__main__":
    main()
