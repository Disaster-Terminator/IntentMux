from __future__ import annotations

from datetime import UTC, datetime

from router.observability import audit_log_day, redact_prompt_text, request_format_signals


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
