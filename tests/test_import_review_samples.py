from __future__ import annotations

import pytest

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
