from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from router.routing import RoutingDecision


LOGGER_NAME = "intentmux"
DEFAULT_AUDIT_LOG_TIMEZONE = "Asia/Shanghai"


@dataclass(frozen=True)
class RequestIdentity:
    value: str
    source: str


class AuditLogger:
    def __init__(
        self,
        log_dir: str | None,
        *,
        enabled: bool = False,
        timezone_name: str = DEFAULT_AUDIT_LOG_TIMEZONE,
    ):
        self.enabled = enabled
        self.log_dir = Path(log_dir) if log_dir else None
        self.timezone_name = timezone_name
        if self.enabled and self.log_dir is not None:
            self.log_dir.mkdir(parents=True, exist_ok=True)

    def write(self, record: dict[str, Any]) -> None:
        if not self.enabled or self.log_dir is None:
            return
        path = self.log_dir / f"{audit_log_day(timezone_name=self.timezone_name)}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


class RouteCounters:
    """Low-cardinality runtime counters derived from route audit records."""

    DURATION_BUCKETS = (
        (100.0, "le_100ms"),
        (1_000.0, "le_1s"),
        (10_000.0, "le_10s"),
        (60_000.0, "le_60s"),
    )
    UNKNOWN = "unknown"

    def __init__(self) -> None:
        self.total = 0
        self.by_event: Counter[str] = Counter()
        self.by_route_id: Counter[str] = Counter()
        self.by_policy_id: Counter[str] = Counter()
        self.by_outcome: Counter[str] = Counter()
        self.by_error_class: Counter[str] = Counter()
        self.by_route_vector_source: Counter[str] = Counter()
        self.by_duration_bucket: Counter[str] = Counter()

    def record(self, record: dict[str, Any]) -> None:
        self.total += 1
        self.by_event[self._string_value(record.get("event"))] += 1
        self.by_route_id[self._string_value(record.get("route_id"))] += 1
        self.by_policy_id[self._string_value(record.get("policy_id"))] += 1
        self.by_outcome[self._string_value(record.get("outcome"))] += 1
        self.by_route_vector_source[
            self._string_value(record.get("route_vector_source"))
        ] += 1
        error_class = record.get("error_class")
        if isinstance(error_class, str) and error_class:
            self.by_error_class[error_class] += 1
        self.by_duration_bucket[
            duration_bucket(number_or_none(record.get("duration_ms")))
        ] += 1

    def snapshot(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "by_event": sorted_counter(self.by_event),
            "by_route_id": sorted_counter(self.by_route_id),
            "by_policy_id": sorted_counter(self.by_policy_id),
            "by_outcome": sorted_counter(self.by_outcome),
            "by_error_class": sorted_counter(self.by_error_class),
            "by_route_vector_source": sorted_counter(self.by_route_vector_source),
            "by_duration_bucket": sorted_counter(self.by_duration_bucket),
        }

    def _string_value(self, value: Any) -> str:
        return value if isinstance(value, str) and value else self.UNKNOWN


def sorted_counter(counter: Counter[str]) -> dict[str, int]:
    return dict(sorted(counter.items()))


def duration_bucket(duration_ms: float | None) -> str:
    if duration_ms is None:
        return "unknown"
    for upper_bound, label in RouteCounters.DURATION_BUCKETS:
        if duration_ms <= upper_bound:
            return label
    return "gt_60s"


def number_or_none(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) else None


class PromptReviewLogger:
    def __init__(
        self,
        log_dir: str | None,
        *,
        mode: str = "off",
        timezone_name: str = DEFAULT_AUDIT_LOG_TIMEZONE,
        max_chars: int = 20_000,
    ):
        self.mode = mode
        self.enabled = mode != "off"
        self.log_dir = Path(log_dir) if log_dir else None
        self.timezone_name = timezone_name
        self.max_chars = max_chars
        if self.enabled:
            if self.log_dir is None:
                raise ValueError(
                    "prompt_log_dir is required when prompt logging is enabled"
                )
            self.log_dir.mkdir(parents=True, exist_ok=True)

    def write(
        self,
        *,
        request_id: str,
        request_id_source: str,
        latest_user_text: str,
        decision: RoutingDecision,
        stream: bool,
    ) -> None:
        if not self.enabled or self.log_dir is None:
            return
        text = latest_user_text[: self.max_chars]
        if self.mode == "redacted":
            text = redact_prompt_text(text)
        record = {
            "event": "prompt_review",
            "latest_user_text": text,
            "mode": self.mode,
            "policy_id": decision.policy_id,
            "reason": decision.reason,
            "request_id": request_id,
            "request_id_source": request_id_source,
            "route_id": decision.route_id,
            "source_model": decision.source_model,
            "stream": stream,
            "target_model": decision.target_model,
            "truncated": len(latest_user_text) > self.max_chars,
            "ts": datetime.now(UTC).isoformat(),
        }
        add_decision_explainability(record, decision)
        add_match_provenance(record, decision)
        add_embedding_diagnostics(record, decision)
        path = self.log_dir / f"{audit_log_day(timezone_name=self.timezone_name)}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


SECRET_PATTERNS = (
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(
        r"\b[A-Z0-9_]*(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD)\s*[:=]\s*\S{8,}",
        re.IGNORECASE,
    ),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"\bsk-proj-[A-Za-z0-9_-]{8,}"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bark-[A-Za-z0-9-]{20,}"),
    re.compile(r"\bms-[A-Za-z0-9_-]{8,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"\b[A-Za-z0-9+/]{80,}={0,2}\b"),
)

SAFE_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
UNSAFE_REQUEST_ID_SUBSTRINGS = ("bearer", "sk-", "api_key", "authorization")


def redact_prompt_text(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def request_format_signals(payload: dict[str, Any]) -> dict[str, Any]:
    messages = payload.get("messages")
    message_list = messages if isinstance(messages, list) else []
    role_counts: dict[str, int] = {
        "assistant": 0,
        "system": 0,
        "tool": 0,
        "user": 0,
    }
    approx_input_chars = 0
    multimodal_content = False
    tool_call_count = 0
    for message in message_list:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if isinstance(role, str) and role in role_counts:
            role_counts[role] += 1
        content = message.get("content")
        content_chars, content_multimodal = content_shape(content)
        approx_input_chars += content_chars
        multimodal_content = multimodal_content or content_multimodal
        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list):
            tool_call_count += len(tool_calls)

    tools = payload.get("tools")
    functions = payload.get("functions")
    return {
        "approx_input_chars": approx_input_chars,
        "assistant_message_count": role_counts["assistant"],
        "function_count": len(functions) if isinstance(functions, list) else 0,
        "functions_present": isinstance(functions, list) and bool(functions),
        "message_count": len(message_list),
        "multimodal_content": multimodal_content,
        "response_format_present": payload.get("response_format") is not None,
        "system_message_count": role_counts["system"],
        "tool_call_count": tool_call_count,
        "tool_choice_present": payload.get("tool_choice") is not None,
        "tool_count": len(tools) if isinstance(tools, list) else 0,
        "tool_history": role_counts["tool"] > 0 or tool_call_count > 0,
        "tool_message_count": role_counts["tool"],
        "tools_present": isinstance(tools, list) and bool(tools),
        "user_message_count": role_counts["user"],
    }


def content_shape(content: Any) -> tuple[int, bool]:
    if isinstance(content, str):
        return len(content), False
    if not isinstance(content, list):
        return 0, False
    chars = 0
    multimodal = False
    for part in content:
        if isinstance(part, str):
            chars += len(part)
            continue
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if isinstance(text, str):
            chars += len(text)
        part_type = part.get("type")
        if part_type not in (None, "text", "input_text"):
            multimodal = True
    return chars, multimodal


def audit_log_day(
    now: datetime | None = None,
    *,
    timezone_name: str = DEFAULT_AUDIT_LOG_TIMEZONE,
) -> str:
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return now.astimezone(zoneinfo_for(timezone_name)).date().isoformat()


def zoneinfo_for(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown timezone: {timezone_name}") from exc


def request_id_from_request(headers: dict[str, str], payload: dict[str, Any]) -> str:
    return request_identity_from_request(headers, payload).value


def request_identity_from_request(
    headers: dict[str, str], payload: dict[str, Any]
) -> RequestIdentity:
    metadata = payload.get("metadata")
    metadata_request_id = None
    if isinstance(metadata, dict):
        metadata_request_id = metadata.get("semantic_router_request_id")
    request_id = safe_request_id(headers.get("x-request-id"))
    if request_id:
        return RequestIdentity(request_id, "x-request-id")
    correlation_id = safe_request_id(headers.get("x-correlation-id"))
    if correlation_id:
        return RequestIdentity(correlation_id, "x-correlation-id")
    trace_id = trace_id_from_traceparent(headers.get("traceparent"))
    if trace_id:
        return RequestIdentity(trace_id, "traceparent")
    metadata_request_id = safe_request_id(metadata_request_id)
    if metadata_request_id:
        return RequestIdentity(
            metadata_request_id, "metadata.semantic_router_request_id"
        )
    return RequestIdentity(str(uuid.uuid4()), "generated")


def safe_request_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    if not SAFE_REQUEST_ID_RE.fullmatch(value):
        return None
    lowered = value.lower()
    if any(token in lowered for token in UNSAFE_REQUEST_ID_SUBSTRINGS):
        return None
    return value


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
    expose_target_model: bool = True,
) -> dict[str, str]:
    from urllib.parse import quote

    headers = {
        "x-router-request-id": quote(request_id, safe=":._-"),
        "x-router-reason": quote(reason, safe=":._-"),
    }
    if expose_target_model:
        headers["x-router-target-model"] = quote(target_model, safe=":._-")
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
    timings_ms: dict[str, float] | None = None,
    format_signals: dict[str, Any] | None = None,
    audit_metadata: dict[str, Any] | None = None,
    usage: dict[str, Any] | None = None,
    audit_logger: AuditLogger | None = None,
    route_counters: RouteCounters | None = None,
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
        timings_ms=timings_ms,
        format_signals=format_signals,
        audit_metadata=audit_metadata,
        usage=usage,
    )
    emit_route_record(logger, record, audit_logger)
    if route_counters is not None:
        route_counters.record(record)


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
    timings_ms: dict[str, float] | None = None,
    format_signals: dict[str, Any] | None = None,
    audit_metadata: dict[str, Any] | None = None,
    audit_logger: AuditLogger | None = None,
    route_counters: RouteCounters | None = None,
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
        timings_ms=timings_ms,
        format_signals=format_signals,
        audit_metadata=audit_metadata,
    )
    record.update(
        {
            "error_class": error_class_for(error, upstream_status),
            "error_type": type(error).__name__,
        }
    )
    emit_route_record(logger, record, audit_logger)
    if route_counters is not None:
        route_counters.record(record)


def error_class_for(error: BaseException, upstream_status: int | None) -> str:
    if upstream_status == 401:
        return "upstream_auth_error"
    if upstream_status == 429:
        return "upstream_rate_limited"
    if upstream_status is not None and upstream_status >= 500:
        return "upstream_server_error"

    error_type = type(error).__name__
    if error_type in {"TimeoutError", "ReadTimeout", "ConnectTimeout", "PoolTimeout"}:
        return "upstream_timeout"
    if error_type in {"RemoteProtocolError", "ConnectError", "NetworkError"}:
        return "upstream_network_error"
    if error_type == "UpstreamStatusError":
        return "upstream_bad_response"
    return "gateway_internal_error"


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
    timings_ms: dict[str, float] | None = None,
    format_signals: dict[str, Any] | None = None,
    audit_metadata: dict[str, Any] | None = None,
    usage: dict[str, Any] | None = None,
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
        "status": upstream_status,
        "target_model": decision.target_model,
        "ts": datetime.now(UTC).isoformat(),
    }
    if upstream_status is not None:
        record["upstream_status"] = upstream_status
    add_decision_explainability(record, decision)
    add_match_provenance(record, decision)
    add_embedding_diagnostics(record, decision)
    if format_signals:
        record["format_signals"] = format_signals
    if audit_metadata:
        record.update(safe_audit_metadata(audit_metadata))
    if usage:
        record.update(safe_usage_metadata(usage))
    if timings_ms:
        for name, duration_ms in timings_ms.items():
            record[name] = round(duration_ms, 2)
    return record


SAFE_AUDIT_METADATA_FIELDS = {
    "config_source",
    "config_sha256",
    "route_bank_sha256",
}


def safe_audit_metadata(metadata: dict[str, Any]) -> dict[str, str]:
    return {
        key: value
        for key in SAFE_AUDIT_METADATA_FIELDS
        if isinstance((value := metadata.get(key)), str) and value
    }


USAGE_FIELDS = ("prompt_tokens", "completion_tokens", "total_tokens")


def safe_usage_metadata(usage: dict[str, Any]) -> dict[str, int]:
    return {
        key: value
        for key in USAGE_FIELDS
        if isinstance((value := usage.get(key)), int) and value >= 0
    }


def add_decision_explainability(
    record: dict[str, Any], decision: RoutingDecision
) -> None:
    if decision.score_margin is not None:
        record["score_margin"] = decision.score_margin
    if decision.threshold is not None:
        record["threshold"] = decision.threshold
    if decision.margin is not None:
        record["margin"] = decision.margin
    if decision.top_route_id is not None:
        record["top_route_id"] = decision.top_route_id
    if decision.second_route_id is not None:
        record["second_route_id"] = decision.second_route_id


def add_match_provenance(record: dict[str, Any], decision: RoutingDecision) -> None:
    if decision.match_source is not None:
        record["match_source"] = decision.match_source
    if decision.match_index is not None:
        record["match_index"] = decision.match_index
    if decision.match_text_sha256 is not None:
        record["match_text_sha256"] = decision.match_text_sha256
    if decision.match_score is not None:
        record["match_score"] = decision.match_score
    if decision.match_provenance is not None:
        record["match_provenance"] = decision.match_provenance


def add_embedding_diagnostics(
    record: dict[str, Any], decision: RoutingDecision
) -> None:
    if decision.route_vector_source is not None:
        record["route_vector_source"] = decision.route_vector_source
    if decision.route_vector_load_ms is not None:
        record["route_vector_load_ms"] = decision.route_vector_load_ms
    if decision.query_embedding_ms is not None:
        record["query_embedding_ms"] = decision.query_embedding_ms


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
