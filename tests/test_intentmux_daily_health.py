from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from scripts.intentmux_daily_health import (
    build_e2e_cmd,
    build_quality_artifact_paths,
    default_log_dir,
    log_consistency_from_day_logs,
    run_quality_artifacts,
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
        "request_id=95647be4-11e1-4d16-9d69-d085c0bb9720 route=lite "
        "target=lite-upstream reason=low_confidence upstream_status=200"
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
                "- duration_ms=117919.39 request_id=req-1 route=lite",
            ],
        },
        "route_summary_all_logs": {"exit_code": 0, "highlights": []},
        "traffic_evidence": {
            "ok": False,
            "today_records": 0,
            "min_records": 10,
            "detail": "insufficient_samples: today_records=0 min_records=10",
        },
        "log_consistency": {
            "ok": False,
            "detail": "duplicates_or_mismatches_detected",
            "route_records": 2,
            "route_unique_request_ids": 2,
            "route_duplicate_request_ids": 0,
            "route_duplicate_records": 0,
            "route_missing_request_id": 0,
            "prompt_records": 3,
            "prompt_unique_request_ids": 3,
            "prompt_duplicate_request_ids": 0,
            "prompt_duplicate_records": 0,
            "prompt_missing_request_id": 0,
            "prompt_recent_in_grace": 0,
            "route_without_prompt": 0,
            "prompt_without_route": 1,
            "prompt_log_exists": True,
        },
        "strict_budget": {"exit_code": 1, "reasons": []},
        "tolerant_budget": {"exit_code": 0, "reasons": []},
        "e2e": {"mode": "skipped", "exit_code": 0, "highlights": []},
        "quality_artifacts": {
            "dir": "/tmp/logs/quality/2026-05-12",
            "route_summary_today_json": {
                "exit_code": 0,
                "path": "/tmp/logs/quality/2026-05-12/route-summary-today.json",
            },
            "evals": {
                "current-router": {
                    "exit_code": 0,
                    "json": "/tmp/logs/quality/2026-05-12/eval-current-router.json",
                },
                "always-lite": {
                    "exit_code": 1,
                    "json": "/tmp/logs/quality/2026-05-12/eval-always-lite.json",
                },
            },
            "route_quality_report": {
                "exit_code": 0,
                "json": "/tmp/logs/quality/2026-05-12/route-quality.json",
                "md": "/tmp/logs/quality/2026-05-12/route-quality.md",
            },
            "review_candidates": {
                "exit_code": 0,
                "json": "/tmp/logs/quality/2026-05-12/review-candidates.json",
                "md": "/tmp/logs/quality/2026-05-12/review-candidates.md",
            },
            "ai_review_packet": {
                "exit_code": 0,
                "json": "/tmp/logs/quality/2026-05-12/ai-review-packet.json",
                "md": "/tmp/logs/quality/2026-05-12/ai-review-packet.md",
            },
        },
        "paths": {"json": "/tmp/report.json", "md": "/tmp/report.md"},
    }

    md = render_md(report)

    assert "- slow_requests:\n  - duration_ms=117919.39 request_id=req-1 route=lite" in md
    assert "## traffic_evidence" in md
    assert "- ok: False" in md
    assert "- detail: insufficient_samples: today_records=0 min_records=10" in md
    assert "## log_consistency" in md
    assert "- prompt_without_route: 1" in md
    assert "## quality_artifacts" in md
    assert "- dir: /tmp/logs/quality/2026-05-12" in md
    assert "- current-router: exit_code=0 json=/tmp/logs/quality/2026-05-12/eval-current-router.json" in md
    assert "- ai_review_packet: exit_code=0 json=/tmp/logs/quality/2026-05-12/ai-review-packet.json md=/tmp/logs/quality/2026-05-12/ai-review-packet.md" in md


def test_traffic_evidence_passes_when_min_valid_route_records_is_met(tmp_path: Path):
    day_log = tmp_path / "2026-05-13.jsonl"
    day_log.write_text(
        "\n".join(
            [
                '{"event":"route_complete","route_id":"lite"}',
                "not-json",
                '{"event":"unrelated"}',
                '{"event":"route_error","route_id":"deep"}',
            ]
        ),
        encoding="utf-8",
    )

    evidence = traffic_evidence_from_day_log(day_log, min_records=2)

    assert evidence == {
        "ok": True,
        "today_records": 2,
        "min_records": 2,
        "detail": "sufficient_samples: today_records=2 min_records=2",
    }


def test_traffic_evidence_fails_when_min_records_is_not_met(tmp_path: Path):
    day_log = tmp_path / "2026-05-13.jsonl"
    day_log.write_text('{"event":"unrelated"}\nnot-json\n', encoding="utf-8")

    evidence = traffic_evidence_from_day_log(day_log, min_records=1)

    assert evidence == {
        "ok": False,
        "today_records": 0,
        "min_records": 1,
        "detail": "insufficient_samples: today_records=0 min_records=1",
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


def test_log_consistency_counts_duplicates_and_prompt_mismatches(tmp_path: Path):
    routes = tmp_path / "routes.jsonl"
    prompts = tmp_path / "prompts.jsonl"
    routes.write_text(
        "\n".join(
            [
                '{"event":"route_complete","request_id":"req-1"}',
                '{"event":"route_error","request_id":"req-1"}',
                '{"event":"route_complete","request_id":"req-route-only"}',
                '{"event":"route_complete"}',
            ]
        ),
        encoding="utf-8",
    )
    prompts.write_text(
        "\n".join(
            [
                '{"event":"prompt_review","request_id":"req-1","latest_user_text":"secret prompt"}',
                '{"event":"prompt_review","request_id":"req-prompt-only","latest_user_text":"private"}',
                '{"event":"prompt_review","request_id":"req-prompt-only","latest_user_text":"private duplicate"}',
                '{"event":"other","request_id":"ignored"}',
            ]
        ),
        encoding="utf-8",
    )

    consistency = log_consistency_from_day_logs(routes, prompts)

    assert consistency == {
        "route_records": 4,
        "route_unique_request_ids": 2,
        "route_duplicate_request_ids": 1,
        "route_duplicate_records": 1,
        "route_missing_request_id": 1,
        "prompt_records": 3,
        "prompt_unique_request_ids": 2,
        "prompt_duplicate_request_ids": 1,
        "prompt_duplicate_records": 1,
        "prompt_missing_request_id": 0,
        "prompt_recent_in_grace": 0,
        "route_without_prompt": 1,
        "prompt_without_route": 1,
        "prompt_log_exists": True,
        "ok": False,
        "detail": "duplicates_or_mismatches_detected",
    }


def test_log_consistency_treats_missing_prompt_log_as_optional(tmp_path: Path):
    routes = tmp_path / "routes.jsonl"
    prompts = tmp_path / "missing-prompts.jsonl"
    routes.write_text(
        "\n".join(
            [
                '{"event":"route_complete","request_id":"req-1"}',
                '{"event":"route_complete","request_id":"req-2"}',
            ]
        ),
        encoding="utf-8",
    )

    consistency = log_consistency_from_day_logs(routes, prompts)

    assert consistency["ok"] is True
    assert consistency["detail"] == "prompt_log_missing_or_disabled"
    assert consistency["prompt_log_exists"] is False
    assert consistency["prompt_recent_in_grace"] == 0
    assert consistency["route_without_prompt"] == 0
    assert consistency["prompt_without_route"] == 0


def test_log_consistency_output_does_not_include_prompt_text(tmp_path: Path):
    routes = tmp_path / "routes.jsonl"
    prompts = tmp_path / "prompts.jsonl"
    routes.write_text('{"event":"route_complete","request_id":"req-1"}\n', encoding="utf-8")
    prompts.write_text(
        '{"event":"prompt_review","request_id":"req-1","latest_user_text":"do not leak"}\n',
        encoding="utf-8",
    )

    consistency = log_consistency_from_day_logs(routes, prompts)
    rendered = render_md(
        {
            "time": "2026-05-12T21:00:00+08:00",
            "repo": "/repo",
            "commit": "abc123",
            "ready": {"ok": True, "summary": "ready=True"},
            "route_summary_today": {"exit_code": 0, "highlights": []},
            "route_summary_all_logs": {"exit_code": 0, "highlights": []},
            "traffic_evidence": {
                "ok": True,
                "today_records": 1,
                "min_records": 0,
                "detail": "not_required",
            },
            "log_consistency": consistency,
            "strict_budget": {"exit_code": 0, "reasons": []},
            "tolerant_budget": {"exit_code": 0, "reasons": []},
            "e2e": {"mode": "skipped", "exit_code": 0, "highlights": []},
            "quality_artifacts": None,
            "paths": {"json": "/tmp/report.json", "md": "/tmp/report.md"},
        }
    )

    assert "do not leak" not in rendered
    assert "- prompt_records: 1" in rendered


def test_log_consistency_ignores_recent_orphan_prompt_within_grace(tmp_path: Path):
    routes = tmp_path / "routes.jsonl"
    prompts = tmp_path / "prompts.jsonl"
    routes.write_text('{"event":"route_complete","request_id":"req-1"}\n', encoding="utf-8")
    prompts.write_text(
        "\n".join(
            [
                (
                    '{"event":"prompt_review","request_id":"req-recent",'
                    '"ts":"2026-05-16T10:00:00+00:00"}'
                ),
                (
                    '{"event":"prompt_review","request_id":"req-old",'
                    '"ts":"2026-05-16T09:50:00+00:00"}'
                ),
            ]
        ),
        encoding="utf-8",
    )

    consistency = log_consistency_from_day_logs(
        routes,
        prompts,
        now=datetime(2026, 5, 16, 10, 1, tzinfo=UTC),
        prompt_grace_seconds=300,
    )

    assert consistency["prompt_recent_in_grace"] == 1
    assert consistency["prompt_without_route"] == 1


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


def test_default_log_dir_uses_intentmux_home_when_log_dir_env_is_unset(
    tmp_path: Path, monkeypatch
):
    runtime_home = tmp_path / "intentmux-home"
    monkeypatch.delenv("INTENTMUX_LOG_DIR", raising=False)
    monkeypatch.setenv("INTENTMUX_HOME", str(runtime_home))

    assert default_log_dir() == runtime_home / "logs"


def test_default_log_dir_uses_ignored_repo_runtime_home_by_default(monkeypatch):
    monkeypatch.delenv("INTENTMUX_LOG_DIR", raising=False)
    monkeypatch.delenv("INTENTMUX_HOME", raising=False)

    assert default_log_dir() == Path(".intentmux-home") / "logs"


def test_default_log_dir_prefers_explicit_log_dir_env(tmp_path: Path, monkeypatch):
    runtime_home = tmp_path / "intentmux-home"
    explicit_logs = tmp_path / "logs"
    monkeypatch.setenv("INTENTMUX_HOME", str(runtime_home))
    monkeypatch.setenv("INTENTMUX_LOG_DIR", str(explicit_logs))

    assert default_log_dir() == explicit_logs


def test_build_e2e_cmd_sources_env_file_only_when_provided():
    cmd = build_e2e_cmd(
        litellm_base_url="http://127.0.0.1:4000",
        router_base_url="http://127.0.0.1:4001",
        log_container="intentmux",
        litellm_env=Path("/runtime/litellm.env"),
    )

    assert ". /runtime/litellm.env" in cmd
    assert "--litellm-base-url http://127.0.0.1:4000" in cmd
    assert "--router-base-url http://127.0.0.1:4001" in cmd
    assert "--log-container intentmux" in cmd


def test_build_e2e_cmd_does_not_hardcode_local_litellm_env():
    cmd = build_e2e_cmd(
        litellm_base_url="http://127.0.0.1:4000",
        router_base_url="http://127.0.0.1:4001",
        log_container="intentmux",
        litellm_env=None,
    )

    assert "set -a;" not in cmd
    assert cmd.startswith("uv run python scripts/e2e_litellm_entry.py")


def test_build_quality_artifact_paths_stay_under_log_dir():
    paths = build_quality_artifact_paths(Path("/data/logs"), "2026-05-18")

    assert paths["dir"] == "/data/logs/quality/2026-05-18"
    assert paths["route_summary_today_json"] == "/data/logs/quality/2026-05-18/route-summary-today.json"
    assert paths["eval_json"]["current-router"] == "/data/logs/quality/2026-05-18/eval-current-router.json"
    assert paths["route_quality_json"] == "/data/logs/quality/2026-05-18/route-quality.json"
    assert paths["review_candidates_json"] == "/data/logs/quality/2026-05-18/review-candidates.json"
    assert paths["ai_review_packet_json"] == "/data/logs/quality/2026-05-18/ai-review-packet.json"


def test_run_quality_artifacts_writes_generic_outputs_without_raw_prompt_mode(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    log_dir = tmp_path / "logs"
    routes_dir = log_dir / "routes"
    prompts_dir = log_dir / "prompts"
    routes_dir.mkdir(parents=True)
    prompts_dir.mkdir(parents=True)
    day_log = routes_dir / "2026-05-18.jsonl"
    prompt_log = prompts_dir / "2026-05-18.jsonl"
    day_log.write_text('{"event":"route_complete","request_id":"req-1"}\n', encoding="utf-8")
    prompt_log.write_text('{"event":"prompt_review","request_id":"req-1","latest_user_text":"private"}\n', encoding="utf-8")
    commands: list[str] = []

    def fake_runner(cmd: str, *, cwd: Path, timeout: int = 120):
        commands.append(cmd)
        parts = cmd.split()
        if "router_log_summary.py" in cmd and "--json" in parts:
            return {"ok": True, "exit_code": 0, "stdout": '{"total": 1}', "stderr": "", "cmd": cmd}
        for option in ("--json-output", "--markdown-output"):
            if option in parts:
                output = Path(parts[parts.index(option) + 1])
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text("{}\n", encoding="utf-8")
        return {"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "cmd": cmd}

    artifacts = run_quality_artifacts(
        repo=repo,
        log_dir=log_dir,
        day="2026-05-18",
        day_log=day_log,
        prompt_day_log=prompt_log,
        slow_request_limit=10,
        runner=fake_runner,
    )

    assert artifacts["route_summary_today_json"]["exit_code"] == 0
    assert artifacts["review_candidates"]["exit_code"] == 0
    assert artifacts["ai_review_packet"]["exit_code"] == 0
    assert artifacts["evals"]["current-router"]["exit_code"] == 0
    assert artifacts["route_quality_report"]["exit_code"] == 0
    assert Path(artifacts["ai_review_packet"]["json"]).exists()
    assert any(
        "scripts/eval_routes.py" in cmd
        and "--cases examples/eval_bank.sample.yaml" in cmd
        and "--baseline current-router" in cmd
        for cmd in commands
    )
    assert any(
        "scripts/route_quality_report.py" in cmd
        and "--route-bank examples/route_bank.sample.yaml" in cmd
        for cmd in commands
    )
    assert any("scripts/select_review_candidates.py" in cmd and "--prompt-path" in cmd for cmd in commands)
    assert any("scripts/prepare_ai_review_packet.py" in cmd for cmd in commands)
    assert not any("--include-prompt-text raw_local" in cmd for cmd in commands)
