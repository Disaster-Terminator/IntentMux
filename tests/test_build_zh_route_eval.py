from __future__ import annotations

from pathlib import Path

import pytest

from scripts.build_zh_route_eval import load_curated_samples, validate_source_manifest


def test_validate_source_manifest_requires_known_slices():
    manifest = {
        "sources": [
            {
                "name": "massive_zh_general",
                "slice": "fast_general_zh",
                "route": "fast",
                "kind": "huggingface",
                "homepage": "https://example.test",
                "license_id": "CC-BY-4.0",
                "license_url": "https://example.test/license",
                "redistributable": True,
                "commercial_use": True,
                "derived_prompt_allowed": "yes",
                "commit_policy": "sample_only",
            }
        ]
    }

    validate_source_manifest(manifest)


def test_validate_source_manifest_rejects_unknown_slice():
    manifest = {
        "sources": [
            {
                "name": "bad",
                "slice": "misc",
                "route": "fast",
                "kind": "manual",
                "homepage": "https://example.test",
                "license_id": "unknown",
                "license_url": "https://example.test/license",
                "redistributable": False,
                "commercial_use": False,
                "derived_prompt_allowed": "review_required",
                "commit_policy": "manifest_only",
            }
        ]
    }

    with pytest.raises(ValueError, match="unknown slice"):
        validate_source_manifest(manifest)


def test_load_curated_samples_preserves_slice_route_and_source(tmp_path: Path):
    sample = tmp_path / "samples.yaml"
    sample.write_text(
        """
samples:
  - id: borderline_001
    slice: borderline_zh
    text: 这个网关方案会不会导致上下文泄漏、路由回归或成本失控？
    expect: strong
    source: curated_borderline_zh
    label_policy: manual_review_required
    rationale: 工程风险、隐私和成本回归需要强模型复核。
    redacted: true
""",
        encoding="utf-8",
    )

    assert load_curated_samples(sample) == [
        {
            "id": "borderline_001",
            "slice": "borderline_zh",
            "text": "这个网关方案会不会导致上下文泄漏、路由回归或成本失控？",
            "expect": "strong",
            "source": "curated_borderline_zh",
            "label_policy": "manual_review_required",
            "rationale": "工程风险、隐私和成本回归需要强模型复核。",
            "redacted": True,
        }
    ]
