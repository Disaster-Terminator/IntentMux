from __future__ import annotations

import pytest

from scripts.preflight import (
    CheckResult,
    require_header,
    require_json_field,
    summarize_results,
)


def test_require_header_returns_pass_for_expected_header():
    result = require_header(
        name="nonstream_route",
        headers={"x-router-target-model": "pro-router"},
        key="x-router-target-model",
        expected="pro-router",
    )

    assert result == CheckResult("nonstream_route", True, "x-router-target-model=pro-router")


def test_require_header_returns_failure_for_missing_header():
    result = require_header(
        name="stream_route",
        headers={},
        key="x-router-target-model",
        expected="pro-router",
    )

    assert result.ok is False
    assert "missing" in result.detail


def test_require_json_field_validates_health_payload():
    result = require_json_field(
        name="health",
        payload={"status": "ok"},
        key="status",
        expected="ok",
    )

    assert result.ok is True


def test_summarize_results_exits_nonzero_when_any_check_fails():
    results = [
        CheckResult("health", True, "ok"),
        CheckResult("stream", False, "wrong route"),
    ]

    with pytest.raises(SystemExit) as exc:
        summarize_results(results)

    assert exc.value.code == 1
