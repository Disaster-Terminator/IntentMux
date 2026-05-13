from __future__ import annotations

from datetime import UTC, datetime

from router.observability import audit_log_day


def test_audit_log_day_defaults_to_beijing_time():
    now = datetime(2026, 5, 13, 16, 30, tzinfo=UTC)

    assert audit_log_day(now) == "2026-05-14"


def test_audit_log_day_can_use_utc_when_configured():
    now = datetime(2026, 5, 13, 16, 30, tzinfo=UTC)

    assert audit_log_day(now, timezone_name="UTC") == "2026-05-13"
