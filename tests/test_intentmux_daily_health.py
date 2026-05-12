from __future__ import annotations

from scripts.intentmux_daily_health import keep, parse_ready, render_md


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
        "strict_budget": {"exit_code": 1, "reasons": []},
        "tolerant_budget": {"exit_code": 0, "reasons": []},
        "e2e": {"mode": "skipped", "exit_code": 0, "highlights": []},
        "paths": {"json": "/tmp/report.json", "md": "/tmp/report.md"},
    }

    md = render_md(report)

    assert "- slow_requests:\n  - duration_ms=117919.39 request_id=req-1 route=fast" in md
