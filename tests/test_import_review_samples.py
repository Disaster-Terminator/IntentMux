from __future__ import annotations

import json

import pytest

from scripts.import_review_samples import ReviewSampleError, convert_review_samples, main


def test_convert_review_samples_accepts_only_redacted_cases():
    raw_lines = [
        '{"text":"这个真实问题为什么偶发","expect":"pro-router","redacted":true,"source":"prod_review","note":"misrouted cheap"}',
        '{"text":"帮我润色这句话","expect":"cheap-router","redacted":true}',
    ]

    result, summary = convert_review_samples(raw_lines)

    assert result == {
        "cases": [
            {
                "text": "这个真实问题为什么偶发",
                "expect": "pro-router",
                "source": "production_review:prod_review",
                "note": "misrouted cheap",
            },
            {
                "text": "帮我润色这句话",
                "expect": "cheap-router",
                "source": "production_review",
            },
        ]
    }
    assert summary["accepted_case_count"] == 2


def test_convert_review_samples_rejects_unredacted_cases():
    raw_lines = [
        '{"text":"raw production prompt","expect":"pro-router","redacted":false}',
    ]

    with pytest.raises(ReviewSampleError, match="redacted=true"):
        convert_review_samples(raw_lines)


def test_convert_review_samples_rejects_unknown_route():
    raw_lines = [
        '{"text":"sample","expect":"unknown-router","redacted":true}',
    ]

    with pytest.raises(ReviewSampleError, match="unknown expect route"):
        convert_review_samples(raw_lines)


def test_convert_review_samples_deduplicates_text():
    raw_lines = [
        '{"text":"重复样本","expect":"pro-router","redacted":true}',
        '{"text":"重复样本","expect":"pro-router","redacted":true}',
    ]

    result, summary = convert_review_samples(raw_lines)

    assert result == {
        "cases": [
            {
                "text": "重复样本",
                "expect": "pro-router",
                "source": "production_review",
            }
        ]
    }
    assert summary["duplicate_text_count"] == 1


def test_main_dry_run_does_not_write_output_and_reports_summary(tmp_path, monkeypatch, capsys):
    input_path = tmp_path / "samples.jsonl"
    output_path = tmp_path / "out.yaml"
    input_path.write_text(
        "\n".join(
            [
                '{"text":"alpha","expect":"cheap-router","redacted":true}',
                "",
                '{"text":"alpha","expect":"cheap-router","redacted":true}',
                '{"text":"beta","expect":"pro-router","redacted":true}',
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "import_review_samples.py",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--dry-run",
            "--summary-json",
        ],
    )

    main()

    assert not output_path.exists()
    summary = json.loads(capsys.readouterr().out.strip())
    assert summary == {
        "accepted_case_count": 2,
        "duplicate_text_count": 1,
        "input_line_count": 4,
        "route_counts": {
            "cheap-router": 1,
            "free-probe-router": 0,
            "pro-router": 1,
        },
        "skipped_blank_line_count": 1,
    }


def test_main_default_write_behavior_still_writes_yaml(tmp_path, monkeypatch):
    input_path = tmp_path / "samples.jsonl"
    output_path = tmp_path / "out.yaml"
    input_path.write_text(
        '{"text":"hello","expect":"free-probe-router","redacted":true}',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "import_review_samples.py",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ],
    )

    main()

    assert output_path.exists()
    output_text = output_path.read_text(encoding="utf-8")
    assert "free-probe-router" in output_text
    assert "hello" in output_text


def test_main_invalid_unredacted_input_fails_before_writing(tmp_path, monkeypatch):
    input_path = tmp_path / "samples.jsonl"
    output_path = tmp_path / "out.yaml"
    input_path.write_text(
        '{"text":"raw","expect":"pro-router","redacted":false}',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "import_review_samples.py",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ],
    )

    with pytest.raises(ReviewSampleError, match="redacted=true"):
        main()
    assert not output_path.exists()
