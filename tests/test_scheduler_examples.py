from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WRAPPER = REPO_ROOT / "examples" / "schedulers" / "intentmux-daily-health.sh"
PATROL_HANDOFF = REPO_ROOT / "docs" / "PATROL_HANDOFF.md"
AGENTS = REPO_ROOT / "AGENTS.md"


def test_scheduler_wrapper_is_generic_and_repo_local_by_default():
    text = WRAPPER.read_text(encoding="utf-8")

    assert "scripts/intentmux_daily_health.py" in text
    assert ".intentmux-home" in text
    assert "/home/private-user" not in text
    assert "Hermes" not in text
    assert "job_id" not in text


def test_patrol_handoff_marks_scheduler_state_as_local_only():
    text = PATROL_HANDOFF.read_text(encoding="utf-8")

    assert "examples/schedulers/intentmux-daily-health.sh" in text
    assert "Hermes cron wrapper paths" in text
    assert "job IDs" in text
    assert "not IntentMux source files" in text


def test_project_agents_file_does_not_include_workstation_absolute_paths():
    text = AGENTS.read_text(encoding="utf-8")

    assert "@/home/private-user" not in text
    assert "/path/to/gateway" not in text
