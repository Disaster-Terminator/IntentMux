from __future__ import annotations

from datetime import UTC, datetime

from router.observability import redact_prompt_text, audit_log_day


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
