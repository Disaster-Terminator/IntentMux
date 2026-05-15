from __future__ import annotations

from typing import Any

KNOWN_SLICES = {
    "fast_general_zh",
    "fast_intent_zh",
    "strong_code_zh",
    "strong_reasoning_zh",
    "strong_long_context_zh",
    "high_risk_zh",
    "borderline_zh",
}

KNOWN_ROUTES = {"fast", "strong"}


def validate_source_manifest(manifest: dict[str, Any]) -> None:
    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("sources must be a non-empty list")
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            raise ValueError(f"source #{index} must be an object")
        name = source.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError(f"source #{index} must set name")
        slice_name = source.get("slice")
        if slice_name not in KNOWN_SLICES:
            raise ValueError(f"source {name}: unknown slice {slice_name!r}")
        route = source.get("route")
        if route not in KNOWN_ROUTES:
            raise ValueError(f"source {name}: unknown route {route!r}")
        for key in (
            "kind",
            "homepage",
            "license_id",
            "license_url",
            "redistributable",
            "commercial_use",
            "derived_prompt_allowed",
            "commit_policy",
        ):
            if key in {"redistributable", "commercial_use"}:
                if not isinstance(source.get(key), bool):
                    raise ValueError(f"source {name}: missing {key}")
                continue
            if not isinstance(source.get(key), str) or not source[key]:
                raise ValueError(f"source {name}: missing {key}")
