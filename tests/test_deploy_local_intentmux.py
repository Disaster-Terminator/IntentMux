from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "deploy_local_intentmux.sh"


def run_script(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=REPO_ROOT,
        env=merged_env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_deploy_script_dry_run_is_parameterized(tmp_path: Path):
    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text("services: {}\n", encoding="utf-8")

    result = run_script(
        "--dry-run",
        "--allow-dirty",
        env={
            "INTENTMUX_COMPOSE_FILE": str(compose_file),
            "INTENTMUX_BASE_URL": "http://127.0.0.1:4999",
        },
    )

    assert result.returncode == 0, result.stderr
    assert str(compose_file) in result.stdout
    assert "/path/to/docker-compose.yml" not in result.stdout
    assert "docker compose" in result.stdout
    assert "build intentmux" in result.stdout
    assert "up -d intentmux" in result.stdout
    assert "wait for http://127.0.0.1:4999/ready" in result.stdout
    assert "wait for container intentmux to become healthy" in result.stdout
    assert "scripts/preflight.py --router-base-url http://127.0.0.1:4999" in result.stdout
    assert "uv run python -c" in result.stdout
    assert "agent_signal" in result.stdout


def test_deploy_script_does_not_sync_runtime_config_by_default(tmp_path: Path):
    compose_file = tmp_path / "docker-compose.yml"
    runtime_config = tmp_path / "runtime" / "config" / "routes.yaml"
    compose_file.write_text("services: {}\n", encoding="utf-8")
    runtime_config.parent.mkdir(parents=True)
    runtime_config.write_text("old\n", encoding="utf-8")

    result = run_script(
        "--dry-run",
        "--allow-dirty",
        env={
            "INTENTMUX_COMPOSE_FILE": str(compose_file),
            "INTENTMUX_RUNTIME_CONFIG": str(runtime_config),
        },
    )

    assert result.returncode == 0, result.stderr
    assert "sync runtime config" not in result.stdout.lower()
    assert "cp config/routes.yaml" not in result.stdout


def test_deploy_script_sync_runtime_config_requires_runtime_path(tmp_path: Path):
    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text("services: {}\n", encoding="utf-8")

    result = run_script(
        "--dry-run",
        "--allow-dirty",
        "--sync-runtime-config",
        env={"INTENTMUX_COMPOSE_FILE": str(compose_file)},
    )

    assert result.returncode != 0
    assert "INTENTMUX_RUNTIME_CONFIG is required" in result.stderr


def test_deploy_script_sync_runtime_config_is_explicit(tmp_path: Path):
    compose_file = tmp_path / "docker-compose.yml"
    runtime_config = tmp_path / "runtime" / "config" / "routes.yaml"
    compose_file.write_text("services: {}\n", encoding="utf-8")
    runtime_config.parent.mkdir(parents=True)
    runtime_config.write_text("old\n", encoding="utf-8")

    result = run_script(
        "--dry-run",
        "--allow-dirty",
        "--sync-runtime-config",
        env={
            "INTENTMUX_COMPOSE_FILE": str(compose_file),
            "INTENTMUX_RUNTIME_CONFIG": str(runtime_config),
        },
    )

    assert result.returncode == 0, result.stderr
    assert f"cp {runtime_config}" in result.stdout
    assert "config/routes.yaml" in result.stdout
