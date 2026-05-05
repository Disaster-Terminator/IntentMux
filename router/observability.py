from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

from router.routing import RoutingDecision


LOGGER_NAME = "gateway_semantic_router"


@dataclass(frozen=True)
class RequestIdentity:
    value: str
    source: str


def request_id_from_request(headers: dict[str, str], payload: dict[str, Any]) -> str:
    return request_identity_from_request(headers, payload).value


def request_identity_from_request(
    headers: dict[str, str], payload: dict[str, Any]
) -> RequestIdentity:
    metadata = payload.get("metadata")
    metadata_request_id = None
    if isinstance(metadata, dict):
        metadata_request_id = metadata.get("semantic_router_request_id")
    user_request_id = payload.get("user")
    if not isinstance(user_request_id, str):
        user_request_id = None
    if headers.get("x-request-id"):
        return RequestIdentity(headers["x-request-id"], "x-request-id")
    if headers.get("x-correlation-id"):
        return RequestIdentity(headers["x-correlation-id"], "x-correlation-id")
    trace_id = trace_id_from_traceparent(headers.get("traceparent"))
    if trace_id:
        return RequestIdentity(trace_id, "traceparent")
    if metadata_request_id:
        return RequestIdentity(metadata_request_id, "metadata.semantic_router_request_id")
    if user_request_id:
        return RequestIdentity(user_request_id, "user")
    return RequestIdentity(str(uuid.uuid4()), "generated")


def trace_id_from_traceparent(traceparent: str | None) -> str | None:
    if not traceparent:
        return None
    parts = traceparent.split("-")
    if len(parts) != 4:
        return None
    trace_id = parts[1]
    if len(trace_id) != 32 or set(trace_id) == {"0"}:
        return None
    try:
        int(trace_id, 16)
    except ValueError:
        return None
    return trace_id


def now_ms() -> float:
    return time.perf_counter() * 1000


def route_headers(
    target_model: str,
    reason: str,
    request_id: str,
    *,
    route_id: str | None = None,
    policy_id: str | None = None,
) -> dict[str, str]:
    from urllib.parse import quote

    headers = {
        "x-router-request-id": request_id,
        "x-router-target-model": quote(target_model, safe=":._-"),
        "x-router-reason": quote(reason, safe=":._-"),
    }
    if route_id is not None:
        headers["x-router-route-id"] = quote(route_id, safe=":._-")
    if policy_id is not None:
        headers["x-router-policy-id"] = quote(policy_id, safe=":._-")
    return headers


def log_route_complete(
    logger: logging.Logger,
    *,
    request_id: str,
    request_id_source: str,
    decision: RoutingDecision,
    stream: bool,
    upstream_status: int,
    started_ms: float,
) -> None:
    logger.info(
        json.dumps(
            {
                "event": "route_complete",
                "request_id": request_id,
                "request_id_source": request_id_source,
                "source_model": decision.source_model,
                "route_id": decision.route_id,
                "target_model": decision.target_model,
                "policy_id": decision.policy_id,
                "reason": decision.reason,
                "rewrite": decision.rewrite,
                "stream": stream,
                "upstream_status": upstream_status,
                "score": decision.score,
                "second_score": decision.second_score,
                "duration_ms": round(now_ms() - started_ms, 2),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def log_route_error(
    logger: logging.Logger,
    *,
    request_id: str,
    request_id_source: str,
    decision: RoutingDecision,
    stream: bool,
    error: BaseException,
    started_ms: float,
    upstream_status: int | None = None,
) -> None:
    record: dict[str, Any] = {
        "event": "route_error",
        "request_id": request_id,
        "request_id_source": request_id_source,
        "source_model": decision.source_model,
        "route_id": decision.route_id,
        "target_model": decision.target_model,
        "policy_id": decision.policy_id,
        "reason": decision.reason,
        "rewrite": decision.rewrite,
        "stream": stream,
        "error_type": type(error).__name__,
        "score": decision.score,
        "second_score": decision.second_score,
        "duration_ms": round(now_ms() - started_ms, 2),
    }
    if upstream_status is not None:
        record["upstream_status"] = upstream_status
    logger.info(
        json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def configure_logging() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    logging.getLogger(LOGGER_NAME).setLevel(logging.INFO)
