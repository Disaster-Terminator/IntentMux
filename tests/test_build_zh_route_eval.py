from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts.build_zh_route_eval import (
    build_eval_payload,
    load_curated_samples,
    validate_source_manifest,
)


def test_validate_source_manifest_requires_known_slices():
    manifest = {
        "sources": [
            {
                "name": "massive_zh_general",
                "slice": "lite_general_zh",
                "route": "lite",
                "kind": "huggingface",
                "homepage": "https://example.test",
                "license_id": "CC-BY-4.0",
                "license_url": "https://example.test/license",
                "redistributable": True,
                "commercial_use": True,
                "derived_prompt_allowed": "allowed",
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
                "route": "lite",
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


def test_real_zh_route_eval_sources_manifest_validates():
    payload = yaml.safe_load(Path("config/zh_route_eval_sources.yaml").read_text())

    validate_source_manifest(payload)


def test_validate_source_manifest_rejects_non_enum_prompt_policy():
    manifest = {
        "sources": [
            {
                "name": "bad_policy",
                "slice": "lite_general_zh",
                "route": "lite",
                "kind": "manual",
                "homepage": "https://example.test",
                "license_id": "unknown",
                "license_url": "https://example.test/license",
                "redistributable": False,
                "commercial_use": False,
                "derived_prompt_allowed": "yes",
                "commit_policy": "manifest_only",
            }
        ]
    }

    with pytest.raises(ValueError, match="derived_prompt_allowed"):
        validate_source_manifest(manifest)


def test_load_curated_samples_preserves_slice_route_and_source(tmp_path: Path):
    sample = tmp_path / "samples.yaml"
    sample.write_text(
        """
samples:
  - id: borderline_001
    slice: borderline_zh
    text: 这个网关方案会不会导致上下文泄漏、路由回归或成本失控？
    expect: deep
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
            "expect": "deep",
            "source": "curated_borderline_zh",
            "label_policy": "manual_review_required",
            "rationale": "工程风险、隐私和成本回归需要强模型复核。",
            "redacted": True,
        }
    ]


def test_load_curated_samples_rejects_slice_expect_mismatch(tmp_path: Path):
    sample = tmp_path / "samples.yaml"
    sample.write_text(
        """
samples:
  - id: risk_001
    slice: high_risk_zh
    text: 线上服务偶发卡死，帮我定位根因
    expect: lite
    source: curated_high_risk_zh
    rationale: 高风险生产事故不应标为 lite。
    redacted: true
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="expected route"):
        load_curated_samples(sample)


def test_build_eval_payload_rejects_duplicate_ids():
    samples = [
        {
            "id": "lite_001",
            "slice": "lite_general_zh",
            "text": "帮我总结这段话",
            "expect": "lite",
            "source": "curated",
            "rationale": "普通总结请求低风险，适合 lite。",
            "redacted": True,
        },
        {
            "id": "lite_001",
            "slice": "lite_intent_zh",
            "text": "查一下天气",
            "expect": "lite",
            "source": "curated",
            "rationale": "普通意图请求低风险，适合 lite。",
            "redacted": True,
        },
    ]

    with pytest.raises(ValueError, match="duplicate case id"):
        build_eval_payload(samples)


def test_build_eval_payload_preserves_long_context_metadata():
    payload = build_eval_payload(
        [
            {
                "id": "long_001",
                "slice": "deep_long_context_zh",
                "text": "请基于长文档定位冲突结论",
                "expect": "deep",
                "source": "curated",
                "rationale": "长上下文证据需要强模型。",
                "redacted": True,
                "input_chars": 12000,
                "message_count": 3,
                "context_policy": "preserved_length",
            }
        ]
    )

    assert payload["cases"][0]["input_chars"] == 12000
    assert payload["cases"][0]["message_count"] == 3
    assert payload["cases"][0]["context_policy"] == "preserved_length"


def test_build_zh_route_eval_cli_writes_eval_yaml(tmp_path: Path):
    sample = tmp_path / "samples.yaml"
    output = tmp_path / "eval.yaml"
    sample.write_text(
        """
samples:
  - id: lite_001
    slice: lite_general_zh
    text: 帮我总结这段话
    expect: lite
    source: curated
    rationale: 普通总结请求低风险，适合 lite。
    redacted: true
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/build_zh_route_eval.py",
            "--curated-samples",
            str(sample),
            "--output",
            str(output),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "wrote" in result.stdout
    assert "lite_001" in output.read_text(encoding="utf-8")
