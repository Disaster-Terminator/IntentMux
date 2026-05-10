from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from router.routing import RoutingDecision


LOGGER_NAME = "intentmux"


@dataclass(frozen=True)
class RequestIdentity:
    value: str
    source: str


class AuditLogger:
    def __init__(self, log_dir: str | None, *, enabled: bool = False):
        self.enabled = enabled
        self.log_dir = Path(log_dir) if log_dir else None
        if self.enabled:
            if self.log_dir is None:
                raise ValueError("audit_log_dir is required when audit logging is enabled")
            self.log_dir.mkdir(parents=True, exist_ok=True)

    def write(self, record: dict[str, Any]) -> None:
        if not self.enabled or self.log_dir is None:
            return
        path = self.log_dir / f"{datetime.now(UTC).date().isoformat()}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


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
        "x-router-request-id": quote(request_id, safe=":._-"),
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
    audit_logger: AuditLogger | None = None,
) -> None:
    ok = 200 <= upstream_status <= 299
    record = route_record(
        event="route_complete",
        request_id=request_id,
        request_id_source=request_id_source,
        decision=decision,
        stream=stream,
        started_ms=started_ms,
        ok=ok,
        outcome="success" if ok else "upstream_non_200",
        upstream_status=upstream_status,
    )
    emit_route_record(logger, record, audit_logger)


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
    audit_logger: AuditLogger | None = None,
) -> None:
    record = route_record(
        event="route_error",
        request_id=request_id,
        request_id_source=request_id_source,
        decision=decision,
        stream=stream,
        started_ms=started_ms,
        ok=False,
        outcome=(
            "upstream_non_200"
            if upstream_status is not None and not 200 <= upstream_status <= 299
            else "route_error"
        ),
        upstream_status=upstream_status,
    )
    record.update(
        {"error_type": type(error).__name__}
    )
    emit_route_record(logger, record, audit_logger)


def route_record(
    *,
    event: str,
    request_id: str,
    request_id_source: str,
    decision: RoutingDecision,
    stream: bool,
    started_ms: float,
    ok: bool,
    outcome: str,
    upstream_status: int | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "duration_ms": round(now_ms() - started_ms, 2),
        "event": event,
        "ok": ok,
        "outcome": outcome,
        "policy_id": decision.policy_id,
        "reason": decision.reason,
        "request_id": request_id,
        "request_id_source": request_id_source,
        "rewrite": decision.rewrite,
        "route_id": decision.route_id,
        "score": decision.score,
        "second_score": decision.second_score,
        "source_model": decision.source_model,
        "stream": stream,
        "target_model": decision.target_model,
        "ts": datetime.now(UTC).isoformat(),
    }
    if upstream_status is not None:
        record["upstream_status"] = upstream_status
    return record


def emit_route_record(
    logger: logging.Logger,
    record: dict[str, Any],
    audit_logger: AuditLogger | None,
) -> None:
    serialized = json.dumps(record, ensure_ascii=False, sort_keys=True)
    logger.info(serialized)
    if audit_logger is not None:
        audit_logger.write(record)


def configure_logging() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    logging.getLogger(LOGGER_NAME).setLevel(logging.INFO)
