from __future__ import annotations

import json
from pathlib import Path
import pytest
import yaml

from scripts import import_review_samples
from scripts.import_review_samples import ReviewSampleError, convert_review_samples


def test_convert_review_samples_accepts_only_redacted_cases():
    raw_lines = [
        '{"text":"这个真实问题为什么偶发","expect":"strong","redacted":true,"source":"prod_review","note":"misrouted cheap"}',
        '{"text":"帮我润色这句话","expect":"fast","redacted":true}',
    ]

    result = convert_review_samples(raw_lines)

    assert result == {
        "cases": [
            {
                "text": "这个真实问题为什么偶发",
                "expect": "strong",
                "source": "production_review:prod_review",
                "note": "misrouted cheap",
            },
            {
                "text": "帮我润色这句话",
                "expect": "fast",
                "source": "production_review",
            },
        ]
    }


def test_convert_review_samples_rejects_unredacted_cases():
    raw_lines = [
        '{"text":"raw production prompt","expect":"strong","redacted":false}',
    ]

    with pytest.raises(ReviewSampleError, match="redacted=true"):
        convert_review_samples(raw_lines)


def test_convert_review_samples_rejects_empty_route_id():
    raw_lines = [
        '{"text":"sample","expect":" ","redacted":true}',
    ]

    with pytest.raises(ReviewSampleError, match="expect must be a non-empty route_id"):
        convert_review_samples(raw_lines)


def test_convert_review_samples_deduplicates_text():
    raw_lines = [
        '{"text":"重复样本","expect":"strong","redacted":true}',
        '{"text":"重复样本","expect":"strong","redacted":true}',
    ]

    result = convert_review_samples(raw_lines)

    assert result == {
        "cases": [
            {
                "text": "重复样本",
                "expect": "strong",
                "source": "production_review",
            }
        ]
    }


def test_convert_review_samples_validates_expect_against_routes_config():
    raw_lines = [
        '{"text":"合法","expect":"fast","redacted":true}',
    ]

    result = convert_review_samples(raw_lines, allowed_route_ids={"fast", "strong"})
    assert result["cases"][0]["expect"] == "fast"


def test_convert_review_samples_rejects_target_model_name_when_routes_validation_enabled():
    raw_lines = [
        '{"text":"非法","expect":"pro-router","redacted":true}',
    ]

    with pytest.raises(ReviewSampleError, match="not found in routes config"):
        convert_review_samples(raw_lines, allowed_route_ids={"fast", "strong"})


def test_main_dry_run_does_not_write_output_and_prints_summary(tmp_path, monkeypatch, capsys):
    input_path = tmp_path / "samples.jsonl"
    output_path = tmp_path / "out.yaml"
    input_path.write_text(
        '\n'.join([
            '{"text":"a","expect":"strong","redacted":true}',
            '',
            '{"text":"a","expect":"strong","redacted":true}',
            '{"text":"b","expect":"fast","redacted":true}',
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
    assert "routes=[fast=1, strong=1]" in out


def test_main_default_writes_yaml(tmp_path, monkeypatch, capsys):
    input_path = tmp_path / "samples.jsonl"
    output_path = tmp_path / "out.yaml"
    input_path.write_text(
        '{"text":"ok","expect":"experimental","redacted":true}',
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
                "expect": "experimental",
                "source": "production_review",
            }
        ]
    }


def test_main_summary_json_contains_counts_and_output_path(tmp_path, monkeypatch, capsys):
    input_path = tmp_path / "samples.jsonl"
    output_path = tmp_path / "out.yaml"
    input_path.write_text(
        '{"text":"ok","expect":"experimental","redacted":true}',
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
    assert summary["route_counts"] == {"experimental": 1}
    assert summary["output_path"] == str(output_path)


def test_main_invalid_unredacted_input_fails_before_writing(tmp_path, monkeypatch):
    input_path = tmp_path / "samples.jsonl"
    output_path = tmp_path / "out.yaml"
    input_path.write_text(
        '{"text":"raw","expect":"strong","redacted":false}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        ["import_review_samples.py", "--input", str(input_path), "--output", str(output_path)],
    )

    with pytest.raises(ReviewSampleError, match="redacted=true"):
        import_review_samples.main()
    assert not output_path.exists()


def test_synthetic_redacted_fixture_is_strictly_redacted_and_route_id_based():
    fixture_path = Path("tests/samples/redacted_review_samples.synthetic.jsonl")
    lines = fixture_path.read_text(encoding="utf-8").splitlines()
    assert lines

    for line in lines:
        sample = json.loads(line)
        assert sample.get("redacted") is True
        assert isinstance(sample.get("text"), str) and sample["text"].strip()
        assert isinstance(sample.get("expect"), str) and sample["expect"].strip()
        assert sample["expect"] != "pro-router"


def test_synthetic_redacted_fixture_converts_with_route_validation():
    fixture_path = Path("tests/samples/redacted_review_samples.synthetic.jsonl")
    lines = fixture_path.read_text(encoding="utf-8").splitlines()

    result = convert_review_samples(lines, allowed_route_ids={"fast", "strong"})

    assert result == {
        "cases": [
            {
                "text": "[REDACTED] incident triage summary",
                "expect": "strong",
                "source": "production_review:synthetic",
                "note": "operator sanity check",
            }
        ]
    }
