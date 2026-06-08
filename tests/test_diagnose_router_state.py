from __future__ import annotations

import subprocess
import sys

from scripts.diagnose_router_state import main


def test_cli_emits_stable_config_section(capsys):
    exit_code = main(["--routes", "config/routes.yaml"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "[router_config]" in output
    assert "entry_model: intentmux" in output
    assert "fallback_route_id: deep" in output
    assert "route_targets:" in output
    assert "  lite: your-lite-model" in output
    assert "  deep: your-deep-model" in output
    assert "hard_rule_route_ids: deep" in output


def test_cli_with_logs_includes_summary_and_budget_and_redacts_payload(tmp_path, capsys):
    logs_path = tmp_path / "router.ndjson"
    logs_path.write_text(
        "\n".join(
            [
                '{"event":"route_complete","route_id":"lite","target_model":"lite-upstream","reason":"embedding","stream":false}',
                '{"event":"route_error","route_id":"deep","target_model":"deep-upstream","reason":"hard_rule:debug","stream":true,"error_type":"TimeoutError","upstream_status":503,"messages":"secret-prompt","authorization":"Bearer abc"}',
            ]
        ),
        encoding="utf-8",
    )

    exit_code = main(["--routes", "config/routes.yaml", "--logs", str(logs_path)])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "[route_summary]" in output
    assert "[route_error_budget]" in output
    assert "routes: deep=1, lite=1" in output
    assert "error_types: TimeoutError=1" in output
    assert "secret-prompt" not in output
    assert "Bearer abc" not in output
    assert "authorization" not in output.lower()
    assert "messages" not in output.lower()


def test_script_file_execution_from_repo_root():
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/diagnose_router_state.py",
            "--routes",
            "config/routes.yaml",
            "--logs",
            "tests/samples/router_logs.ndjson",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "[router_config]" in completed.stdout
    assert "[route_summary]" in completed.stdout
    assert "[route_error_budget]" in completed.stdout
