from __future__ import annotations

from datetime import UTC, datetime

from router.observability import (
    audit_log_day,
    error_class_for,
    redact_prompt_text,
    request_identity_from_request,
    request_format_signals,
    route_record,
)
from router.routing import RoutingDecision


def test_audit_log_day_defaults_to_beijing_time():
    now = datetime(2026, 5, 13, 16, 30, tzinfo=UTC)

    assert audit_log_day(now) == "2026-05-14"


def test_audit_log_day_can_use_utc_when_configured():
    now = datetime(2026, 5, 13, 16, 30, tzinfo=UTC)

    assert audit_log_day(now, timezone_name="UTC") == "2026-05-13"


def test_redact_prompt_text_masks_common_credentials():
    text = "Authorization: Bearer abcdefghijklmnop and key sk-proj-abcdefghijklmnop"

    redacted = redact_prompt_text(text)

    assert "abcdefghijklmnop" not in redacted
    assert redacted.count("[REDACTED]") == 2


def test_request_format_signals_counts_structure_without_content():
    signals = request_format_signals(
        {
            "messages": [
                {"role": "system", "content": "private system prompt"},
                {"role": "user", "content": "please edit code"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{"id": "call-1", "type": "function"}],
                },
                {"role": "tool", "content": "private tool result"},
            ],
            "tools": [{"type": "function", "function": {"name": "edit_file"}}],
            "tool_choice": "auto",
            "response_format": {"type": "json_object"},
        }
    )

    assert signals == {
        "approx_input_chars": 56,
        "assistant_message_count": 1,
        "function_count": 0,
        "functions_present": False,
        "message_count": 4,
        "multimodal_content": False,
        "response_format_present": True,
        "system_message_count": 1,
        "tool_call_count": 1,
        "tool_choice_present": True,
        "tool_count": 1,
        "tool_history": True,
        "tool_message_count": 1,
        "tools_present": True,
        "user_message_count": 1,
    }

    assert "private" not in str(signals)


def test_request_identity_rejects_secret_bearing_request_id_header():
    identity = request_identity_from_request(
        {"x-request-id": "Bearer sk-secret-token"},
        {},
    )

    assert identity.source == "generated"
    assert identity.value != "Bearer sk-secret-token"


def test_request_identity_rejects_non_ascii_and_whitespace_metadata_id():
    identity = request_identity_from_request(
        {},
        {"metadata": {"semantic_router_request_id": "请求 id"}},
    )

    assert identity.source == "generated"
    assert identity.value != "请求 id"


def test_request_identity_accepts_safe_ascii_token_header():
    identity = request_identity_from_request(
        {"x-request-id": "req-20260516:abc.def_1"},
        {},
    )

    assert identity.source == "x-request-id"
    assert identity.value == "req-20260516:abc.def_1"


def test_route_record_always_includes_status_alias():
    record = route_record(
        event="route_error",
        request_id="req-1",
        request_id_source="generated",
        decision=RoutingDecision(
            target_model="local-deep-model",
            reason="test",
            rewrite=True,
            route_id="deep",
            policy_id="test",
        ),
        stream=False,
        started_ms=0.0,
        ok=False,
        outcome="route_error",
        upstream_status=None,
    )

    assert "status" in record
    assert record["status"] is None
    assert "upstream_status" not in record


def test_route_record_includes_match_provenance_only_when_available():
    without_match = route_record(
        event="route_complete",
        request_id="req-1",
        request_id_source="generated",
        decision=RoutingDecision(
            target_model="local-lite-model",
            reason="low_confidence",
            rewrite=True,
            route_id="lite",
            policy_id="low_confidence",
        ),
        stream=False,
        started_ms=0.0,
        ok=True,
        outcome="success",
        upstream_status=200,
    )
    with_match = route_record(
        event="route_complete",
        request_id="req-2",
        request_id_source="generated",
        decision=RoutingDecision(
            target_model="local-deep-model",
            reason="embedding",
            rewrite=True,
            route_id="deep",
            policy_id="embedding",
            score=0.92,
            second_score=0.31,
            score_margin=0.61,
            threshold=0.4,
            margin=0.04,
            top_route_id="deep",
            second_route_id="lite",
            match_source="swebench_issue_resolution",
            match_index=3,
            match_text_sha256="abc123",
            match_score=0.91,
            match_provenance="aurelio_hybrid_exact",
        ),
        stream=False,
        started_ms=0.0,
        ok=True,
        outcome="success",
        upstream_status=200,
    )

    assert "match_source" not in without_match
    assert with_match["match_source"] == "swebench_issue_resolution"
    assert with_match["match_index"] == 3
    assert with_match["match_text_sha256"] == "abc123"
    assert with_match["match_score"] == 0.91
    assert with_match["match_provenance"] == "aurelio_hybrid_exact"
    assert with_match["score"] == 0.92
    assert with_match["second_score"] == 0.31
    assert with_match["score_margin"] == 0.61
    assert with_match["threshold"] == 0.4
    assert with_match["margin"] == 0.04
    assert with_match["top_route_id"] == "deep"
    assert with_match["second_route_id"] == "lite"


def test_error_class_for_stable_upstream_statuses_and_timeouts():
    assert error_class_for(RuntimeError("unauthorized"), 401) == "upstream_auth_error"
    assert error_class_for(RuntimeError("rate limited"), 429) == "upstream_rate_limited"
    assert error_class_for(RuntimeError("bad gateway"), 503) == "upstream_server_error"
    assert error_class_for(TimeoutError("timeout"), None) == "upstream_timeout"
