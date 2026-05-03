from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from router.routing import RoutingDecision


LOGGER_NAME = "gateway_semantic_router"


def request_id_from_headers(headers: dict[str, str]) -> str:
    return headers.get("x-request-id") or headers.get("x-correlation-id") or str(uuid.uuid4())


def now_ms() -> float:
    return time.perf_counter() * 1000


def route_headers(target_model: str, reason: str, request_id: str) -> dict[str, str]:
    from urllib.parse import quote

    return {
        "x-router-request-id": request_id,
        "x-router-target-model": target_model,
        "x-router-reason": quote(reason, safe=":._-"),
    }


def log_route_complete(
    logger: logging.Logger,
    *,
    request_id: str,
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
                "source_model": decision.source_model,
                "target_model": decision.target_model,
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


def configure_logging() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    logging.getLogger(LOGGER_NAME).setLevel(logging.INFO)
