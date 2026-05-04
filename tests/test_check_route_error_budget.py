from __future__ import annotations

import subprocess
import sys

from scripts.check_route_error_budget import BudgetConfig, check_budget, format_budget_result, main
from scripts.router_log_summary import parse_route_records


def records_from_text(text: str):
    return list(parse_route_records(text.splitlines()))


def test_check_budget_passes_when_no_route_errors():
    records = records_from_text(
        "\n".join(
            [
                '{"event":"route_complete","target_model":"pro-router","stream":true}',
                '{"event":"route_complete","target_model":"cheap-router","stream":false}',
            ]
        )
    )

    result = check_budget(records, BudgetConfig(min_total=2, max_error_rate=0.0))

    assert result.passed is True
    assert result.total == 2
    assert result.errors == 0
    assert result.error_rate == 0.0
    assert result.reasons == []


def test_check_budget_fails_when_error_rate_exceeds_budget():
    records = records_from_text(
        "\n".join(
            [
                '{"event":"route_complete","target_model":"pro-router","stream":true}',
                '{"event":"route_error","target_model":"pro-router","stream":true,"error_type":"RemoteProtocolError"}',
            ]
        )
    )

    result = check_budget(
        records,
        BudgetConfig(
            min_total=1,
            max_error_rate=0.0,
            max_target_error_rate=1.0,
        ),
    )

    assert result.passed is False
    assert result.error_rate == 0.5
    assert result.reasons == ["error_rate 0.5000 exceeds max_error_rate 0.0000"]


def test_check_budget_fails_when_target_error_rate_exceeds_budget():
    records = records_from_text(
        "\n".join(
            [
                '{"event":"route_complete","target_model":"pro-router","stream":true}',
                '{"event":"route_error","target_model":"cheap-router","stream":true,"error_type":"TimeoutError"}',
            ]
        )
    )

    result = check_budget(
        records,
        BudgetConfig(
            min_total=1,
            max_error_rate=1.0,
            max_target_error_rate=0.0,
        ),
    )

    assert result.passed is False
    assert result.target_error_rates == {"pro-router": 0.0, "cheap-router": 1.0}
    assert result.reasons == [
        "target cheap-router error_rate 1.0000 exceeds max_target_error_rate 0.0000"
    ]


def test_check_budget_fails_when_sample_size_is_too_small():
    result = check_budget([], BudgetConfig(min_total=1, max_error_rate=0.0))

    assert result.passed is False
    assert result.total == 0
    assert result.reasons == ["total 0 below min_total 1"]


def test_format_budget_result_is_stable_for_runbooks():
    records = records_from_text(
        "\n".join(
            [
                '{"event":"route_complete","target_model":"pro-router","stream":true}',
                '{"event":"route_error","target_model":"cheap-router","stream":true,"error_type":"TimeoutError"}',
            ]
        )
    )
    result = check_budget(
        records,
        BudgetConfig(min_total=1, max_error_rate=1.0, max_target_error_rate=1.0),
    )

    assert format_budget_result(result) == "\n".join(
        [
            "PASS route_error_budget",
            "total=2 completed=1 errors=1 error_rate=0.5000",
            "target_error_rates: cheap-router=1.0000, pro-router=0.0000",
            "error_types: TimeoutError=1",
        ]
    )


def test_cli_returns_zero_when_budget_passes(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "stdin",
        [
            '{"event":"route_complete","target_model":"pro-router","stream":true}\n',
        ],
    )

    exit_code = main(["--min-total", "1"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert output.startswith("PASS route_error_budget\n")


def test_cli_returns_nonzero_when_budget_fails(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "stdin",
        [
            '{"event":"route_error","target_model":"pro-router","stream":true,"error_type":"RemoteProtocolError"}\n',
        ],
    )

    exit_code = main(["--min-total", "1"])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert output.startswith("FAIL route_error_budget\n")
    assert "RemoteProtocolError=1" in output


def test_script_file_execution_works_from_repo_root():
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/check_route_error_budget.py",
            "--min-total",
            "1",
        ],
        input='{"event":"route_complete","target_model":"pro-router"}\n',
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stdout.startswith("PASS route_error_budget\n")
