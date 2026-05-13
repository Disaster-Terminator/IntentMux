from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from scripts.intentmux_daily_health import (
    build_e2e_cmd,
    traffic_evidence_from_day_log,
    keep,
    parse_ready,
    path_from_arg_or_env,
    render_md,
    report_now_and_day,
)


def test_parse_ready_reads_components_contract():
    ok, summary, detail = parse_ready(
        {
            "ready": True,
            "components": {
                "router": {"ok": True, "detail": None},
                "embedding": {"ok": True, "detail": "status=200"},
                "litellm": {"ok": True, "detail": "status=401 auth_required"},
            },
        },
        200,
        None,
    )

    assert ok is True
    assert summary == (
        "ready=True router=True embedding=True "
        "litellm_ok=True litellm_detail=status=401 auth_required"
    )
    assert detail == {
        "http": 200,
        "ready": True,
        "router_ok": True,
        "embedding_ok": True,
        "litellm_ok": True,
        "litellm_detail": "status=401 auth_required",
        "error": None,
    }


def test_keep_preserves_slow_request_rows_without_truncating():
    slow_row = (
        "- duration_ms=117919.39 timestamp=2026-05-12T06:32:48.781826+00:00 "
        "request_id=95647be4-11e1-4d16-9d69-d085c0bb9720 route=fast "
        "target=cheap-router reason=low_confidence upstream_status=200"
    )
    summary = "\n".join(
        [
            "total=207 completed=207 errors=0 streams=205 nonstreams=2",
            "slow_requests:",
            slow_row,
        ]
    )

    highlights = keep(summary, ["total", "slow_requests", "duration_ms"])

    assert highlights == [
        "total=207 completed=207 errors=0 streams=205 nonstreams=2",
        "slow_requests:",
        slow_row,
    ]


def test_render_md_nests_slow_request_rows():
    report = {
        "time": "2026-05-12T21:00:00+08:00",
        "repo": "/repo",
        "commit": "abc123",
        "ready": {"ok": True, "summary": "ready=True"},
        "route_summary_today": {
            "exit_code": 0,
            "highlights": [
                "slow_requests:",
                "- duration_ms=117919.39 request_id=req-1 route=fast",
            ],
        },
        "route_summary_all_logs": {"exit_code": 0, "highlights": []},
        "traffic_evidence": {
            "ok": False,
            "today_records": 0,
            "min_records": 10,
            "detail": "insufficient_samples: today_records=0 min_records=10",
        },
        "strict_budget": {"exit_code": 1, "reasons": []},
        "tolerant_budget": {"exit_code": 0, "reasons": []},
        "e2e": {"mode": "skipped", "exit_code": 0, "highlights": []},
        "paths": {"json": "/tmp/report.json", "md": "/tmp/report.md"},
    }

    md = render_md(report)

    assert "- slow_requests:\n  - duration_ms=117919.39 request_id=req-1 route=fast" in md
    assert "## traffic_evidence" in md
    assert "- ok: False" in md
    assert "- detail: insufficient_samples: today_records=0 min_records=10" in md


def test_traffic_evidence_passes_when_min_records_is_met(tmp_path: Path):
    day_log = tmp_path / "2026-05-13.jsonl"
    day_log.write_text("{}\n{}\n", encoding="utf-8")

    evidence = traffic_evidence_from_day_log(day_log, min_records=2)

    assert evidence == {
        "ok": True,
        "today_records": 2,
        "min_records": 2,
        "detail": "sufficient_samples: today_records=2 min_records=2",
    }


def test_traffic_evidence_fails_when_min_records_is_not_met(tmp_path: Path):
    day_log = tmp_path / "2026-05-13.jsonl"
    day_log.write_text("{}\n", encoding="utf-8")

    evidence = traffic_evidence_from_day_log(day_log, min_records=2)

    assert evidence == {
        "ok": False,
        "today_records": 1,
        "min_records": 2,
        "detail": "insufficient_samples: today_records=1 min_records=2",
    }


def test_traffic_evidence_is_not_required_by_default(tmp_path: Path):
    day_log = tmp_path / "missing.jsonl"

    evidence = traffic_evidence_from_day_log(day_log, min_records=0)

    assert evidence == {
        "ok": True,
        "today_records": 0,
        "min_records": 0,
        "detail": "not_required",
    }


def test_report_day_defaults_to_beijing_time():
    now, day = report_now_and_day(
        now=datetime(2026, 5, 13, 16, 30, tzinfo=UTC),
        timezone_name="Asia/Shanghai",
        explicit_date=None,
    )

    assert day == "2026-05-14"
    assert now.isoformat() == "2026-05-14T00:30:00+08:00"


def test_report_day_accepts_explicit_date_override():
    _, day = report_now_and_day(
        now=datetime(2026, 5, 13, 16, 30, tzinfo=UTC),
        timezone_name="Asia/Shanghai",
        explicit_date="2026-05-10",
    )

    assert day == "2026-05-10"


def test_path_from_arg_or_env_prefers_cli_value(monkeypatch):
    monkeypatch.setenv("INTENTMUX_LOG_DIR", "/env/logs")

    path = path_from_arg_or_env("/cli/logs", "INTENTMUX_LOG_DIR", Path("logs"))

    assert path == Path("/cli/logs")


def test_path_from_arg_or_env_uses_env_before_default(monkeypatch):
    monkeypatch.setenv("INTENTMUX_LOG_DIR", "/env/logs")

    path = path_from_arg_or_env(None, "INTENTMUX_LOG_DIR", Path("logs"))

    assert path == Path("/env/logs")


def test_build_e2e_cmd_sources_env_file_only_when_provided():
    cmd = build_e2e_cmd(
        litellm_base_url="http://127.0.0.1:4000",
        log_container="intentmux",
        litellm_env=Path("/runtime/litellm.env"),
    )

    assert ". /runtime/litellm.env" in cmd
    assert "--litellm-base-url http://127.0.0.1:4000" in cmd
    assert "--log-container intentmux" in cmd


def test_build_e2e_cmd_does_not_hardcode_local_litellm_env():
    cmd = build_e2e_cmd(
        litellm_base_url="http://127.0.0.1:4000",
        log_container="intentmux",
        litellm_env=None,
    )

    assert "set -a;" not in cmd
    assert cmd.startswith("uv run python scripts/e2e_litellm_entry.py")
