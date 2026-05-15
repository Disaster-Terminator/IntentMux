from __future__ import annotations

import pytest

from scripts.build_zh_route_eval import validate_source_manifest


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
