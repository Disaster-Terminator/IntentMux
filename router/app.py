from __future__ import annotations

import json
import logging
import secrets
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from router.config import RouterSettings, load_settings
from router.embedding import OpenAIEmbeddingClient
from router.observability import (
    AuditLogger,
    PromptReviewLogger,
    configure_logging,
    log_route_complete,
    log_route_error,
    now_ms,
    request_identity_from_request,
    request_format_signals,
    route_headers,
)
from router.proxy import LiteLLMProxy
from router.readiness import ReadinessChecker
from router.routing import Router, latest_user_text


logger = logging.getLogger("intentmux")
STREAMING_SAFETY_HEADERS = {
    "cache-control": "no-cache, no-transform",
    "x-accel-buffering": "no",
}


class UpstreamStatusError(Exception):
    def __init__(self, status_code: int):
        super().__init__(f"upstream returned status {status_code}")
        self.status_code = status_code


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
            OpenAIEmbeddingClient(
                settings.embedding_url,
                settings.embedding_model,
                timeout=settings.embedding_timeout,
                batch_size=settings.embedding_batch_size,
                api_key=settings.embedding_api_key,
                headers=settings.embedding_headers,
                input_max_chars=settings.embedding_input_max_chars,
            ),
        )
    if proxy is None:
        proxy = LiteLLMProxy(
            settings.litellm_base_url,
            timeout=settings.litellm_timeout,
            api_key=settings.litellm_api_key,
        )
    if readiness_checker is None:
        readiness_checker = ReadinessChecker(settings)
    audit_logger = AuditLogger(
        settings.audit_log_dir,
        enabled=settings.audit_log_enabled,
        timezone_name=settings.audit_log_timezone,
    )
    prompt_review_logger = PromptReviewLogger(
        settings.prompt_log_dir,
        mode=settings.prompt_log_mode,
        timezone_name=settings.audit_log_timezone,
        max_chars=settings.prompt_log_max_chars,
    )
    audit_metadata = route_audit_metadata(settings)

    app = FastAPI(title="IntentMux")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    async def parse_json_object(request: Request) -> Any:
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return JSONResponse(
                status_code=400,
                content={"error": {"message": "Invalid JSON request body"}},
            )
        if not isinstance(payload, dict):
            return JSONResponse(
                status_code=400,
                content={"error": {"message": "JSON body must be an object"}},
            )
        return payload

    def require_inbound_auth(request: Request) -> JSONResponse | None:
        if not settings.inbound_api_keys:
            return None
        actual = request.headers.get("authorization", "")
        for api_key in settings.inbound_api_keys:
            expected = f"Bearer {api_key}"
            if secrets.compare_digest(actual, expected):
                return None
        return JSONResponse(
            status_code=401,
            content={"error": {"message": "Invalid or missing IntentMux API key"}},
            headers={"www-authenticate": "Bearer"},
        )

    @app.get("/v1/models")
    async def models(request: Request) -> JSONResponse:
        auth_error = require_inbound_auth(request)
        if auth_error is not None:
            return auth_error
        return JSONResponse(
            {
                "object": "list",
                "data": [
                    {"id": settings.route_model, "object": "model"},
                    {"id": "lite", "object": "model"},
                    {"id": "deep", "object": "model"},
                ],
            }
        )

    @app.get("/ready")
    async def ready(request: Request) -> JSONResponse:
        if settings.cloud_mode:
            auth_error = require_inbound_auth(request)
            if auth_error is not None:
                return auth_error
        report = await readiness_checker.check()
        return JSONResponse(
            report.to_dict(),
            status_code=200 if report.ready else 503,
        )

    @app.post("/v1/intentmux/decision")
    async def route_decision(request: Request) -> Any:
        auth_error = require_inbound_auth(request)
        if auth_error is not None:
            return auth_error
        payload = await parse_json_object(request)
        if isinstance(payload, JSONResponse):
            return payload
        format_signals = request_format_signals(payload)
        decision = await router.decide(payload, format_signals=format_signals)
        return {
            "source_model": decision.source_model,
            "route_id": decision.route_id,
            "target_model": decision.target_model,
            "policy_id": decision.policy_id,
            "reason": decision.reason,
            "rewrite": decision.rewrite,
            "score": decision.score,
            "second_score": decision.second_score,
            "score_margin": decision.score_margin,
            "threshold": decision.threshold,
            "margin": decision.margin,
            "top_route_id": decision.top_route_id,
            "second_route_id": decision.second_route_id,
            "match_source": decision.match_source,
            "match_index": decision.match_index,
            "match_text_sha256": decision.match_text_sha256,
            "match_score": decision.match_score,
            "match_provenance": decision.match_provenance,
            "route_vector_source": decision.route_vector_source,
            "route_vector_load_ms": decision.route_vector_load_ms,
            "query_embedding_ms": decision.query_embedding_ms,
        }

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> Response:
        started_ms = now_ms()
        request_headers = dict(request.headers)
        auth_error = require_inbound_auth(request)
        if auth_error is not None:
            return auth_error
        payload = await parse_json_object(request)
        if isinstance(payload, JSONResponse):
            return payload
        format_signals = request_format_signals(payload)
        request_identity = request_identity_from_request(request_headers, payload)
        request_id = request_identity.value
        request_headers["x-request-id"] = request_id
        decision_started_ms = now_ms()
        decision = await router.decide(payload, format_signals=format_signals)
        decision_ms = now_ms() - decision_started_ms
        forwarded_payload = sanitize_forwarded_payload(payload, decision.target_model)
        stream = forwarded_payload.get("stream") is True
        prompt_review_logger.write(
            request_id=request_id,
            request_id_source=request_identity.source,
            latest_user_text=latest_user_text(payload.get("messages", [])),
            decision=decision,
            stream=stream,
        )
        router_headers = route_headers(
            decision.target_model,
            decision.reason,
            request_id,
            route_id=decision.route_id,
            policy_id=decision.policy_id,
            expose_target_model=settings.expose_target_model_header,
        )
        if stream:
            upstream_started_ms = now_ms()
            stream_context = proxy.stream_chat(forwarded_payload, request_headers)
            try:
                upstream = await stream_context.__aenter__()
                upstream_headers_ms = now_ms() - upstream_started_ms
            except Exception as exc:
                log_route_error(
                    logger,
                    request_id=request_id,
                    request_id_source=request_identity.source,
                    decision=decision,
                    stream=True,
                    error=exc,
                    started_ms=started_ms,
                    timings_ms={
                        "decision_ms": decision_ms,
                        "upstream_ms": now_ms() - upstream_started_ms,
                    },
                    format_signals=format_signals,
                    audit_metadata=audit_metadata,
                    audit_logger=audit_logger,
                )
                return upstream_error_response(
                    request_id=request_id,
                    decision=decision,
                    error=exc,
                    expose_target_model=settings.expose_target_model_header,
                )
            if is_upstream_failure(upstream.status_code):
                error = UpstreamStatusError(upstream.status_code)
                log_route_error(
                    logger,
                    request_id=request_id,
                    request_id_source=request_identity.source,
                    decision=decision,
                    stream=True,
                    error=error,
                    started_ms=started_ms,
                    upstream_status=upstream.status_code,
                    timings_ms={
                        "decision_ms": decision_ms,
                        "upstream_ms": now_ms() - upstream_started_ms,
                        "upstream_headers_ms": upstream_headers_ms,
                    },
                    format_signals=format_signals,
                    audit_metadata=audit_metadata,
                    audit_logger=audit_logger,
                )
                await stream_context.__aexit__(None, None, None)
                return upstream_error_response(
                    request_id=request_id,
                    decision=decision,
                    error=error,
                    expose_target_model=settings.expose_target_model_header,
                )
            headers = streaming_response_headers(
                dict(upstream.headers),
                router_headers,
            )
            return StreamingResponse(
                stream_with_context(
                    upstream.content,
                    stream_context,
                    request_id=request_id,
                    request_id_source=request_identity.source,
                    decision=decision,
                    upstream_status=upstream.status_code,
                    started_ms=started_ms,
                    decision_ms=decision_ms,
                    upstream_started_ms=upstream_started_ms,
                    upstream_headers_ms=upstream_headers_ms,
                    format_signals=format_signals,
                    audit_metadata=audit_metadata,
                    audit_logger=audit_logger,
                ),
                status_code=upstream.status_code,
                headers=headers,
                media_type=headers.get("content-type", "text/event-stream"),
            )

        upstream_started_ms = now_ms()
        try:
            upstream = await proxy.forward_chat(forwarded_payload, request_headers)
            upstream_ms = now_ms() - upstream_started_ms
        except Exception as exc:
            log_route_error(
                logger,
                request_id=request_id,
                request_id_source=request_identity.source,
                decision=decision,
                stream=False,
                error=exc,
                started_ms=started_ms,
                timings_ms={
                    "decision_ms": decision_ms,
                    "upstream_ms": now_ms() - upstream_started_ms,
                },
                format_signals=format_signals,
                audit_metadata=audit_metadata,
                audit_logger=audit_logger,
            )
            return upstream_error_response(
                request_id=request_id,
                decision=decision,
                error=exc,
                expose_target_model=settings.expose_target_model_header,
            )
        if is_upstream_failure(upstream.status_code):
            error = UpstreamStatusError(upstream.status_code)
            log_route_error(
                logger,
                request_id=request_id,
                request_id_source=request_identity.source,
                decision=decision,
                stream=False,
                error=error,
                started_ms=started_ms,
                upstream_status=upstream.status_code,
                timings_ms={
                    "decision_ms": decision_ms,
                    "upstream_ms": upstream_ms,
                },
                format_signals=format_signals,
                audit_metadata=audit_metadata,
                audit_logger=audit_logger,
            )
            return upstream_error_response(
                request_id=request_id,
                decision=decision,
                error=error,
                expose_target_model=settings.expose_target_model_header,
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
            timings_ms={
                "decision_ms": decision_ms,
                "upstream_ms": upstream_ms,
            },
            format_signals=format_signals,
            audit_metadata=audit_metadata,
            usage=usage_from_response_content(upstream.content),
            audit_logger=audit_logger,
        )
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=headers,
            media_type=headers.get("content-type"),
        )

    return app


def sanitize_forwarded_payload(
    payload: dict[str, Any], target_model: str
) -> dict[str, Any]:
    forwarded = dict(payload)
    forwarded["model"] = target_model
    metadata = forwarded.get("metadata")
    if isinstance(metadata, dict):
        metadata = dict(metadata)
        for key in ("route_id", "route", "target_route", "semantic_router_request_id"):
            metadata.pop(key, None)
        if metadata:
            forwarded["metadata"] = metadata
        else:
            forwarded.pop("metadata", None)
    return forwarded


def route_audit_metadata(settings: RouterSettings) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for key in ("config_source", "config_sha256", "route_bank_sha256"):
        value = getattr(settings, key)
        if isinstance(value, str) and value:
            metadata[key] = value
    return metadata


def usage_from_response_content(content: bytes) -> dict[str, int] | None:
    try:
        payload = json.loads(content)
    except (TypeError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None
    safe_usage = {
        key: value
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        if isinstance((value := usage.get(key)), int) and value >= 0
    }
    return safe_usage or None


async def stream_with_context(
    body_iterator,
    stream_context,
    *,
    request_id: str,
    request_id_source: str,
    decision,
    upstream_status: int,
    started_ms: float,
    decision_ms: float = 0.0,
    upstream_started_ms: float | None = None,
    upstream_headers_ms: float | None = None,
    format_signals: dict[str, Any] | None = None,
    audit_metadata: dict[str, Any] | None = None,
    audit_logger: AuditLogger | None = None,
):
    if upstream_started_ms is None:
        upstream_started_ms = started_ms
    body_started_ms = now_ms()
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
            timings_ms={
                "decision_ms": decision_ms,
                "upstream_ms": now_ms() - upstream_started_ms,
                "upstream_headers_ms": upstream_headers_ms or 0.0,
                "upstream_body_ms": now_ms() - body_started_ms,
            },
            format_signals=format_signals,
            audit_metadata=audit_metadata,
            audit_logger=audit_logger,
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
                timings_ms={
                    "decision_ms": decision_ms,
                    "upstream_ms": now_ms() - upstream_started_ms,
                    "upstream_headers_ms": upstream_headers_ms or 0.0,
                    "upstream_body_ms": now_ms() - body_started_ms,
                },
                format_signals=format_signals,
                audit_metadata=audit_metadata,
                audit_logger=audit_logger,
            )


def upstream_error_response(
    *,
    request_id: str,
    decision,
    error: BaseException,
    expose_target_model: bool = True,
) -> JSONResponse:
    return JSONResponse(
        {
            "error": {
                "message": "upstream route failed",
                "type": type(error).__name__,
            }
        },
        status_code=502,
        headers=route_headers(
            decision.target_model,
            decision.reason,
            request_id,
            route_id=decision.route_id,
            policy_id=decision.policy_id,
            expose_target_model=expose_target_model,
        ),
    )


def is_upstream_failure(status_code: int) -> bool:
    return status_code >= 500


def streaming_response_headers(
    upstream_headers: dict[str, str],
    router_response_headers: dict[str, str],
) -> dict[str, str]:
    headers = dict(upstream_headers)
    headers.update(STREAMING_SAFETY_HEADERS)
    headers.update(router_response_headers)
    return headers


def main() -> None:
    configure_logging()
    settings = load_settings()
    logger.info(
        "startup config_source=%s config_path=%s runtime_home=%s "
        "runtime_config_exists=%s audit_log_enabled=%s audit_log_dir=%s "
        "access_log=%s prompt_log_mode=%s",
        settings.config_source,
        settings.config_path,
        settings.runtime_home,
        str(settings.runtime_config_exists).lower(),
        str(settings.audit_log_enabled).lower(),
        settings.audit_log_dir,
        str(settings.access_log).lower(),
        settings.prompt_log_mode,
    )
    uvicorn.run(
        create_app(settings=settings),
        host=settings.listen_host,
        port=settings.listen_port,
        access_log=settings.access_log,
    )


if __name__ == "__main__":
    main()
