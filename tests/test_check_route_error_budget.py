from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

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


def test_check_budget_fails_when_not_ok_rate_exceeds_budget():
    records = records_from_text(
        "\n".join(
            [
                '{"event":"route_complete","target_model":"cheap-router","ok":true,"outcome":"success","upstream_status":200}',
                '{"event":"route_complete","target_model":"cheap-router","ok":false,"outcome":"upstream_non_200","upstream_status":400}',
            ]
        )
    )

    result = check_budget(
        records,
        BudgetConfig(
            min_total=1,
            max_error_rate=1.0,
            max_target_error_rate=1.0,
            max_not_ok_rate=0.0,
        ),
    )

    assert result.passed is False
    assert result.not_ok == 1
    assert result.not_ok_rate == 0.5
    assert result.outcome_rates == {"success": 0.5, "upstream_non_200": 0.5}
    assert result.reasons == ["not_ok_rate 0.5000 exceeds max_not_ok_rate 0.0000"]


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


def test_check_budget_includes_route_error_rates_and_handles_missing_route_id():
    records = records_from_text(
        "\n".join(
            [
                '{"event":"route_complete","route_id":"chat.default","target_model":"pro-router"}',
                '{"event":"route_error","route_id":"chat.default","target_model":"cheap-router","error_type":"TimeoutError"}',
                '{"event":"route_error","target_model":"cheap-router","error_type":"TimeoutError"}',
            ]
        )
    )

    result = check_budget(
        records,
        BudgetConfig(min_total=1, max_error_rate=1.0, max_target_error_rate=1.0),
    )

    assert result.route_error_rates == {"chat.default": 0.5, "unknown": 1.0}


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
                '{"event":"route_error","route_id":"chat.default","target_model":"cheap-router","stream":true,"error_type":"TimeoutError"}',
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
            "total=2 completed=1 errors=1 error_rate=0.5000 not_ok=1 not_ok_rate=0.5000",
            "target_error_rates: cheap-router=1.0000, pro-router=0.0000",
            "route_error_rates: chat.default=1.0000, unknown=0.0000",
            "reason_rates: none",
            "outcome_rates: route_error=0.5000, success=0.5000",
            "upstream_status_rates: none",
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


def test_script_file_execution_accepts_log_file_path(tmp_path: Path):
    log_path = tmp_path / "routes.jsonl"
    log_path.write_text(
        "\n".join(
            [
                '{"event":"route_complete","target_model":"cheap-router","ok":true,"outcome":"success","upstream_status":200}',
                '{"event":"route_complete","target_model":"cheap-router","ok":false,"outcome":"upstream_non_200","upstream_status":400}',
            ]
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/check_route_error_budget.py",
            str(log_path),
            "--min-total",
            "1",
            "--max-not-ok-rate",
            "0",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 1
    assert "not_ok_rate 0.5000 exceeds max_not_ok_rate 0.0000" in completed.stdout


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


def test_parse_diagnostic_thresholds_disabled_by_default():
    records = records_from_text('{"event":"route_complete","target_model":"pro-router"}')
    result = check_budget(
        records,
        BudgetConfig(min_total=1, max_error_rate=0.0),
        parse_diagnostics=ParseDiagnostics(
            malformed_json_lines=5,
            missing_event_records=3,
            unknown_event_records=2,
        ),
    )

    assert result.passed is True
    assert result.reasons == []
    assert result.ignored_records == 10


def test_check_budget_fails_when_malformed_json_exceeds_budget():
    records = records_from_text('{"event":"route_complete","target_model":"pro-router"}')
    result = check_budget(
        records,
        BudgetConfig(min_total=1, max_error_rate=0.0, max_malformed_json=0),
        parse_diagnostics=ParseDiagnostics(malformed_json_lines=2),
    )

    assert result.passed is False
    assert "malformed_json 2 exceeds max_malformed_json 0" in result.reasons


def test_check_budget_fails_when_missing_event_exceeds_budget():
    records = records_from_text('{"event":"route_complete","target_model":"pro-router"}')
    result = check_budget(
        records,
        BudgetConfig(min_total=1, max_error_rate=0.0, max_missing_event=0),
        parse_diagnostics=ParseDiagnostics(missing_event_records=1),
    )

    assert result.passed is False
    assert "missing_event 1 exceeds max_missing_event 0" in result.reasons


def test_check_budget_fails_when_unknown_event_exceeds_budget():
    records = records_from_text('{"event":"route_complete","target_model":"pro-router"}')
    result = check_budget(
        records,
        BudgetConfig(min_total=1, max_error_rate=0.0, max_unknown_event=0),
        parse_diagnostics=ParseDiagnostics(unknown_event_records=4),
    )

    assert result.passed is False
    assert "unknown_event 4 exceeds max_unknown_event 0" in result.reasons


def test_check_budget_fails_when_ignored_records_exceeds_budget():
    records = records_from_text('{"event":"route_complete","target_model":"pro-router"}')
    result = check_budget(
        records,
        BudgetConfig(min_total=1, max_error_rate=0.0, max_ignored_records=2),
        parse_diagnostics=ParseDiagnostics(
            malformed_json_lines=1,
            missing_event_records=1,
            unknown_event_records=1,
        ),
    )

    assert result.passed is False
    assert result.ignored_records == 3
    assert "ignored_records 3 exceeds max_ignored_records 2" in result.reasons


def test_cli_fails_when_parse_diagnostics_threshold_exceeded(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "stdin",
        [
            '{"event":"route_complete","target_model":"pro-router"}\n',
            '{"event":"route_error",\n',
        ],
    )

    exit_code = main(["--min-total", "1", "--max-error-rate", "1", "--max-malformed-json", "0"])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "reasons: malformed_json 1 exceeds max_malformed_json 0" in output


def test_cli_json_output_on_passing_budget(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "stdin",
        ['{"event":"route_complete","route_id":"chat.default","target_model":"pro-router","reason":"hard_rule:x"}\n'],
    )

    exit_code = main(["--min-total", "1", "--output", "json"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 0
    assert payload["passed"] is True
    assert payload["total"] == 1
    assert payload["completed"] == 1
    assert payload["errors"] == 0
    assert payload["error_rate"] == 0.0
    assert payload["target_error_rates"] == {"pro-router": 0.0}
    assert payload["route_error_rates"] == {"chat.default": 0.0}
    assert payload["reason_rates"] == {"hard_rule:x": 1.0}
    assert payload["error_types"] == {}
    assert payload["reasons"] == []
    assert payload["ignored_records"] == 0
    assert payload["parse_diagnostics"] == {
        "malformed_json": 0,
        "missing_event": 0,
        "unknown_event": 0,
    }


def test_cli_json_output_on_failing_budget(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "stdin",
        [
            '{"event":"route_error","target_model":"pro-router","error_type":"RemoteProtocolError"}\n',
        ],
    )

    exit_code = main(["--min-total", "1", "--output", "json"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 1
    assert payload["passed"] is False
    assert payload["reasons"] == [
        "error_rate 1.0000 exceeds max_error_rate 0.0000",
        "target pro-router error_rate 1.0000 exceeds max_target_error_rate 0.0000",
    ]


def test_cli_json_output_includes_parse_diagnostics(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "stdin",
        [
            '{"event":"route_complete","target_model":"pro-router"}\n',
            '{"target_model":"cheap-router"}\n',
            '{"event":"route_error",\n',
        ],
    )

    exit_code = main(["--min-total", "1", "--max-error-rate", "1", "--output", "json"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 0
    assert payload["parse_diagnostics"] == {
        "malformed_json": 1,
        "missing_event": 1,
        "unknown_event": 0,
    }
    assert payload["ignored_records"] == 2


def test_cli_json_mode_preserves_nonzero_exit_on_budget_failure(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "stdin",
        ['{"event":"route_complete","target_model":"pro-router"}\n', '{"event":"route_error",\n'],
    )

    exit_code = main(
        ["--min-total", "1", "--max-error-rate", "1", "--max-malformed-json", "0", "--json"]
    )

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 1
    assert payload["passed"] is False
    assert "malformed_json 1 exceeds max_malformed_json 0" in payload["reasons"]

def test_check_budget_passes_when_parse_diagnostic_thresholds_are_met():
    records = records_from_text('{"event":"route_complete","target_model":"pro-router"}')
    result = check_budget(
        records,
        BudgetConfig(
            min_total=1,
            max_error_rate=0.0,
            max_malformed_json=1,
            max_missing_event=1,
            max_unknown_event=1,
            max_ignored_records=3,
        ),
        parse_diagnostics=ParseDiagnostics(
            malformed_json_lines=1,
            missing_event_records=1,
            unknown_event_records=1,
        ),
    )

    assert result.passed is True
    assert result.reasons == []


def test_check_budget_passes_when_reason_rate_is_within_budget():
    records = records_from_text(
        "\n".join(
            [
                '{"event":"route_complete","target_model":"pro-router","reason":"hard_rule:a"}',
                '{"event":"route_complete","target_model":"cheap-router","reason":"hard_rule:b"}',
                '{"event":"route_complete","target_model":"cheap-router","reason":"hard_rule:b"}',
            ]
        )
    )

    result = check_budget(
        records,
        BudgetConfig(
            min_total=3,
            max_error_rate=0.0,
            max_target_error_rate=0.0,
            max_reason_rates={"embedding_error": 0.0},
        ),
    )

    assert result.passed is True
    assert result.reason_rates == {"hard_rule:a": 1 / 3, "hard_rule:b": 2 / 3}
    assert result.reasons == []


def test_check_budget_fails_when_upstream_status_rate_exceeds_budget():
    records = records_from_text(
        "\n".join(
            [
                '{"event":"route_complete","target_model":"cheap-router","upstream_status":200}',
                '{"event":"route_complete","target_model":"cheap-router","upstream_status":400}',
            ]
        )
    )

    result = check_budget(
        records,
        BudgetConfig(
            min_total=2,
            max_error_rate=0.0,
            max_target_error_rate=0.0,
            max_upstream_status_rates={"400": 0.0},
        ),
    )

    assert result.passed is False
    assert result.upstream_status_rates == {"200": 0.5, "400": 0.5}
    assert result.reasons == [
        "upstream_status 400 rate 0.5000 exceeds max_upstream_status_rate 0.0000"
    ]


def test_check_budget_fails_when_route_error_rate_exceeds_global_budget():
    records = records_from_text(
        "\n".join(
            [
                '{"event":"route_complete","route_id":"chat.default","target_model":"pro-router"}',
                '{"event":"route_error","route_id":"chat.default","target_model":"pro-router","error_type":"RemoteProtocolError"}',
            ]
        )
    )
    result = check_budget(
        records,
        BudgetConfig(
            min_total=1,
            max_error_rate=1.0,
            max_target_error_rate=1.0,
            max_route_error_rate=0.0,
        ),
    )
    assert result.passed is False
    assert result.reasons == [
        "route chat.default error_rate 0.5000 exceeds max_route_error_rate 0.0000"
    ]


def test_cli_supports_route_specific_error_rate_budget(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "stdin",
        [
            '{"event":"route_complete","route_id":"chat.default","target_model":"pro-router"}\n',
            '{"event":"route_error","route_id":"chat.default","target_model":"pro-router","error_type":"RemoteProtocolError"}\n',
        ],
    )
    exit_code = main(
        [
            "--min-total",
            "1",
            "--max-error-rate",
            "1",
            "--max-target-error-rate",
            "1",
            "--max-route-error-rate",
            "chat.default=0",
        ]
    )
    output = capsys.readouterr().out
    assert exit_code == 1
    assert "route_error_rates: chat.default=0.5000" in output


def test_cli_accepts_repeatable_upstream_status_rate_budgets(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "stdin",
        [
            '{"event":"route_complete","target_model":"cheap-router","upstream_status":200}\n',
            '{"event":"route_complete","target_model":"cheap-router","upstream_status":400}\n',
        ],
    )

    exit_code = main(
        [
            "--min-total",
            "1",
            "--max-upstream-status-rate",
            "400=0",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "upstream_status_rates: 200=0.5000, 400=0.5000" in output
    assert "upstream_status 400 rate 0.5000 exceeds max_upstream_status_rate 0.0000" in output


def test_script_file_execution_returns_nonzero_for_failing_budget():
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/check_route_error_budget.py",
            "--min-total",
            "1",
            "--max-error-rate",
            "0",
        ],
        input='{"event":"route_error","target_model":"pro-router","error_type":"RemoteProtocolError"}\n',
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    assert completed.stdout.startswith("FAIL route_error_budget\n")
    assert "error_rate 1.0000 exceeds max_error_rate 0.0000" in completed.stdout

def test_contract_fixture_budget_includes_route_and_target_buckets():
    fixture = Path("tests/samples/router_logs_contract.ndjson")
    diagnostics = ParseDiagnostics()
    records = list(parse_route_records(fixture.read_text().splitlines(), diagnostics=diagnostics))

    result = check_budget(
        records,
        BudgetConfig(min_total=1, max_error_rate=1.0, max_target_error_rate=1.0),
        parse_diagnostics=diagnostics,
    )

    assert result.passed is True
    assert result.target_error_rates == {
        "base-router": 0.0,
        "legacy-router": 1.0,
        "pro-router": 0.5,
    }
    assert result.route_error_rates == {"chat.strong": 0.5, "unknown": 0.5}
    assert result.error_types == {"RemoteProtocolError": 1, "UpstreamStatusError": 1}
    assert result.parse_diagnostics.malformed_json_lines == 1
    assert result.parse_diagnostics.unknown_event_records == 1
