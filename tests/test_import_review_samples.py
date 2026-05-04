from __future__ import annotations

import json
import pytest
import yaml

from scripts import import_review_samples
from scripts.import_review_samples import ReviewSampleError, convert_review_samples


def test_convert_review_samples_accepts_only_redacted_cases():
    raw_lines = [
        '{"text":"这个真实问题为什么偶发","expect":"pro-router","redacted":true,"source":"prod_review","note":"misrouted cheap"}',
        '{"text":"帮我润色这句话","expect":"cheap-router","redacted":true}',
    ]

    result = convert_review_samples(raw_lines)

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

    result = convert_review_samples(raw_lines)

    assert result == {
        "cases": [
            {
                "text": "重复样本",
                "expect": "pro-router",
                "source": "production_review",
            }
        ]
    }


def test_main_dry_run_does_not_write_output_and_prints_summary(tmp_path, monkeypatch, capsys):
    input_path = tmp_path / "samples.jsonl"
    output_path = tmp_path / "out.yaml"
    input_path.write_text(
        '\n'.join([
            '{"text":"a","expect":"pro-router","redacted":true}',
            '',
            '{"text":"a","expect":"pro-router","redacted":true}',
            '{"text":"b","expect":"cheap-router","redacted":true}',
        ]),
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
        ],
    )

    import_review_samples.main()
    out = capsys.readouterr().out

    assert not output_path.exists()
    assert "summary:" in out
    assert "accepted_cases=2" in out
    assert "duplicates=1" in out
    assert "blank_lines=1" in out
    assert "routes=[cheap-router=1, pro-router=1]" in out


def test_main_default_writes_yaml(tmp_path, monkeypatch, capsys):
    input_path = tmp_path / "samples.jsonl"
    output_path = tmp_path / "out.yaml"
    input_path.write_text(
        '{"text":"ok","expect":"free-probe-router","redacted":true}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        ["import_review_samples.py", "--input", str(input_path), "--output", str(output_path)],
    )

    import_review_samples.main()
    out = capsys.readouterr().out

    assert output_path.exists()
    assert "wrote" in out
    assert yaml.safe_load(output_path.read_text(encoding="utf-8")) == {
        "cases": [
            {
                "text": "ok",
                "expect": "free-probe-router",
                "source": "production_review",
            }
        ]
    }


def test_main_summary_json_contains_counts_and_output_path(tmp_path, monkeypatch, capsys):
    input_path = tmp_path / "samples.jsonl"
    output_path = tmp_path / "out.yaml"
    input_path.write_text(
        '{"text":"ok","expect":"free-probe-router","redacted":true}',
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
            "--summary-json",
        ],
    )

    import_review_samples.main()
    lines = capsys.readouterr().out.strip().splitlines()
    summary = json.loads(lines[-1])

    assert summary["input_line_count"] == 1
    assert summary["accepted_case_count"] == 1
    assert summary["duplicate_text_count"] == 0
    assert summary["skipped_blank_line_count"] == 0
    assert summary["route_counts"] == {"free-probe-router": 1}
    assert summary["output_path"] == str(output_path)


def test_main_invalid_unredacted_input_fails_before_writing(tmp_path, monkeypatch):
    input_path = tmp_path / "samples.jsonl"
    output_path = tmp_path / "out.yaml"
    input_path.write_text(
        '{"text":"raw","expect":"pro-router","redacted":false}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        ["import_review_samples.py", "--input", str(input_path), "--output", str(output_path)],
    )

    with pytest.raises(ReviewSampleError, match="redacted=true"):
        import_review_samples.main()
    assert not output_path.exists()
