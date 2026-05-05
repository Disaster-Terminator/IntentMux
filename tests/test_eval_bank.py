from __future__ import annotations

from scripts.build_eval_bank import build_eval_bank, load_manual_cases


def test_build_eval_bank_keeps_manual_cases_and_adds_route_bank_cases():
    manual_cases = [
        {"text": "手工 cheap", "expect": "fast"},
        {"text": "手工 pro", "expect": "strong"},
    ]
    route_bank = {
        "routes": {
            "fast": {
                "utterances": [
                    {"text": "生成 cheap 1", "source": "massive"},
                    {"text": "生成 cheap 2", "source": "massive"},
                ]
            },
            "strong": {
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
        {"text": "手工 cheap", "expect": "fast", "source": "manual"},
        {"text": "手工 pro", "expect": "strong", "source": "manual"},
        {"text": "生成 cheap 1", "expect": "fast", "source": "massive"},
        {"text": "generated pro", "expect": "strong", "source": "swebench"},
    ]


def test_build_eval_bank_deduplicates_manual_and_generated_cases():
    manual_cases = [{"text": "重复", "expect": "fast"}]
    route_bank = {
        "routes": {
            "fast": {
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
        {"text": "重复", "expect": "fast", "source": "manual"},
        {"text": "新样本", "expect": "fast", "source": "massive"},
    ]


def test_load_manual_cases_merges_multiple_files(tmp_path):
    first = tmp_path / "eval_cases.yaml"
    first.write_text(
        """
cases:
  - text: 手工 cheap
    expect: fast
""",
        encoding="utf-8",
    )
    second = tmp_path / "review_cases.yaml"
    second.write_text(
        """
cases:
  - text: 生产复核 pro
    expect: strong
    source: production_review
""",
        encoding="utf-8",
    )

    assert load_manual_cases([first, second]) == [
        {"text": "手工 cheap", "expect": "fast"},
        {"text": "生产复核 pro", "expect": "strong", "source": "production_review"},
    ]
