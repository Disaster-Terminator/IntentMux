from __future__ import annotations

import subprocess
import sys

from scripts.check_route_error_budget import BudgetConfig, check_budget, format_budget_result, main
from scripts.router_log_summary import ParseDiagnostics, parse_route_records


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
    assert result.reason_rates == {}
    assert result.reasons == []
    assert result.ignored_records == 0


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


def test_check_budget_fails_when_reason_rate_exceeds_budget():
    records = records_from_text(
        "\n".join(
            [
                (
                    '{"event":"route_complete","target_model":"cheap-router",'
                    '"reason":"embedding_error"}'
                ),
                (
                    '{"event":"route_complete","target_model":"pro-router",'
                    '"reason":"hard_rule:线上"}'
                ),
            ]
        )
    )

    result = check_budget(
        records,
        BudgetConfig(
            min_total=1,
            max_error_rate=0.0,
            max_target_error_rate=0.0,
            max_reason_rates={"embedding_error": 0.0},
        ),
    )

    assert result.passed is False
    assert result.reason_rates == {"embedding_error": 0.5, "hard_rule:线上": 0.5}
    assert result.reasons == [
        "reason embedding_error rate 0.5000 exceeds max_reason_rate 0.0000"
    ]


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
            "reason_rates: none",
            "error_types: TimeoutError=1",
        ]
    )


def test_format_budget_result_reports_parse_diagnostics_when_present():
    result = check_budget(
        [],
        BudgetConfig(min_total=0),
        parse_diagnostics=ParseDiagnostics(
            malformed_json_lines=1,
            missing_event_records=1,
            unknown_event_records=1,
        ),
    )

    assert format_budget_result(result).endswith(
        "parse_diagnostics: malformed_json=1, missing_event=1, unknown_event=1"
    )


def test_check_budget_diagnostic_thresholds_are_disabled_by_default():
    result = check_budget(
        [],
        BudgetConfig(min_total=0),
        parse_diagnostics=ParseDiagnostics(
            malformed_json_lines=3,
            missing_event_records=2,
            unknown_event_records=1,
        ),
    )

    assert result.passed is True
    assert result.reasons == []
    assert result.ignored_records == 6


def test_check_budget_fails_when_malformed_json_exceeds_threshold():
    result = check_budget(
        [],
        BudgetConfig(min_total=0, max_malformed_json=0),
        parse_diagnostics=ParseDiagnostics(malformed_json_lines=2),
    )

    assert result.passed is False
    assert result.reasons == ["malformed_json 2 exceeds max_malformed_json 0"]


def test_check_budget_fails_when_missing_event_exceeds_threshold():
    result = check_budget(
        [],
        BudgetConfig(min_total=0, max_missing_event=0),
        parse_diagnostics=ParseDiagnostics(missing_event_records=2),
    )

    assert result.passed is False
    assert result.reasons == ["missing_event 2 exceeds max_missing_event 0"]


def test_check_budget_fails_when_unknown_event_exceeds_threshold():
    result = check_budget(
        [],
        BudgetConfig(min_total=0, max_unknown_event=0),
        parse_diagnostics=ParseDiagnostics(unknown_event_records=2),
    )

    assert result.passed is False
    assert result.reasons == ["unknown_event 2 exceeds max_unknown_event 0"]


def test_check_budget_fails_when_ignored_records_exceeds_threshold():
    result = check_budget(
        [],
        BudgetConfig(min_total=0, max_ignored_records=2),
        parse_diagnostics=ParseDiagnostics(
            malformed_json_lines=1,
            missing_event_records=1,
            unknown_event_records=1,
        ),
    )

    assert result.passed is False
    assert result.reasons == ["ignored_records 3 exceeds max_ignored_records 2"]


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


def test_cli_accepts_repeatable_reason_rate_budgets(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "stdin",
        [
            (
                '{"event":"route_complete","target_model":"cheap-router",'
                '"reason":"embedding_error"}\n'
            ),
            (
                '{"event":"route_complete","target_model":"pro-router",'
                '"reason":"hard_rule:线上"}\n'
            ),
        ],
    )

    exit_code = main(
        [
            "--min-total",
            "1",
            "--max-reason-rate",
            "embedding_error=0",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "reason_rates: embedding_error=0.5000, hard_rule:线上=0.5000" in output
    assert "reason embedding_error rate 0.5000 exceeds max_reason_rate 0.0000" in output


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


def test_cli_reports_parse_diagnostics_for_malformed_or_partial_logs(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "stdin",
        [
            '{"event":"route_complete","target_model":"pro-router"}\n',
            '{"target_model":"cheap-router"}\n',
            '{"event":"route_error",\n',
        ],
    )

    exit_code = main(["--min-total", "1", "--max-error-rate", "1"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "parse_diagnostics: malformed_json=1" in output
    assert "missing_event=1" in output


def test_cli_fails_when_diagnostic_threshold_exceeded(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "stdin",
        [
            "127.0.0.1 - - [04/May/2026:00:00:00 +0000] GET /healthz 200 2\n",
            '{"event":"route_complete","target_model":"pro-router"}\n',
            '{"event":"route_error",\n',
        ],
    )

    exit_code = main(
        [
            "--min-total",
            "1",
            "--max-error-rate",
            "1",
            "--max-malformed-json",
            "0",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "malformed_json 1 exceeds max_malformed_json 0" in output
