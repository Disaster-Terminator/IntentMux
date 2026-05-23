from __future__ import annotations

from scripts.build_eval_bank import build_eval_bank, load_manual_cases


def test_tracked_example_eval_bank_uses_product_routes_and_public_sources():
    import yaml
    from pathlib import Path

    payload = yaml.safe_load(Path("examples/eval_bank.sample.yaml").read_text(encoding="utf-8"))
    cases = payload["cases"]
    expects = {case["expect"] for case in cases}
    sources = {case.get("source") for case in cases}

    assert expects == {"lite", "deep"}
    assert "lite-upstream" not in str(payload)
    assert "deep-upstream" not in str(payload)
    assert "free-probe-router" not in str(payload)
    assert "massive_zh_cn_general" in sources
    assert "swebench_issue_resolution" in sources
    assert len(cases) >= 4


def test_build_eval_bank_keeps_manual_cases_and_adds_route_bank_cases():
    manual_cases = [
        {"text": "手工 cheap", "expect": "lite"},
        {"text": "手工 pro", "expect": "deep"},
    ]
    route_bank = {
        "routes": {
            "lite": {
                "utterances": [
                    {"text": "生成 cheap 1", "source": "massive"},
                    {"text": "生成 cheap 2", "source": "massive"},
                ]
            },
            "deep": {
                "utterances": [
                    {"text": "generated pro", "source": "swebench"},
                ]
            },
        }
    }

    eval_bank = build_eval_bank(
        manual_cases=manual_cases,
        route_bank=route_bank,
        per_route_limit=1,
    )

    assert eval_bank["cases"] == [
        {"text": "手工 cheap", "expect": "lite", "source": "manual"},
        {"text": "手工 pro", "expect": "deep", "source": "manual"},
        {"text": "生成 cheap 1", "expect": "lite", "source": "massive"},
        {"text": "generated pro", "expect": "deep", "source": "swebench"},
    ]


def test_build_eval_bank_deduplicates_manual_and_generated_cases():
    manual_cases = [{"text": "重复", "expect": "lite"}]
    route_bank = {
        "routes": {
            "lite": {
                "utterances": [
                    {"text": "重复", "source": "massive"},
                    {"text": "新样本", "source": "massive"},
                ]
            }
        }
    }

    eval_bank = build_eval_bank(
        manual_cases=manual_cases,
        route_bank=route_bank,
        per_route_limit=10,
    )

    assert eval_bank["cases"] == [
        {"text": "重复", "expect": "lite", "source": "manual"},
        {"text": "新样本", "expect": "lite", "source": "massive"},
    ]


def test_load_manual_cases_merges_multiple_files(tmp_path):
    first = tmp_path / "eval_cases.yaml"
    first.write_text(
        """
cases:
  - text: 手工 cheap
    expect: lite
""",
        encoding="utf-8",
    )
    second = tmp_path / "review_cases.yaml"
    second.write_text(
        """
cases:
  - text: 生产复核 pro
    expect: deep
    source: production_review
""",
        encoding="utf-8",
    )

    assert load_manual_cases([first, second]) == [
        {"text": "手工 cheap", "expect": "lite"},
        {"text": "生产复核 pro", "expect": "deep", "source": "production_review"},
    ]
