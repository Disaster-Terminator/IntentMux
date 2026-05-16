from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

KNOWN_SLICES = {
    "lite_general_zh",
    "lite_intent_zh",
    "deep_code_zh",
    "deep_reasoning_zh",
    "deep_long_context_zh",
    "high_risk_zh",
    "borderline_zh",
}

KNOWN_ROUTES = {"lite", "deep"}
DERIVED_PROMPT_POLICIES = {"allowed", "review_required", "forbidden"}
COMMIT_POLICIES = {"sample_only", "manifest_only", "never"}
EXPECTED_ROUTES_BY_SLICE = {
    "lite_general_zh": {"lite"},
    "lite_intent_zh": {"lite"},
    "deep_code_zh": {"deep"},
    "deep_reasoning_zh": {"deep"},
    "deep_long_context_zh": {"deep"},
    "high_risk_zh": {"deep"},
    "borderline_zh": {"lite", "deep"},
}
LONG_CONTEXT_POLICIES = {"preserved_length", "summarized", "schema_reserved"}


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
        if source["derived_prompt_allowed"] not in DERIVED_PROMPT_POLICIES:
            raise ValueError(
                f"source {name}: derived_prompt_allowed must be one of "
                f"{sorted(DERIVED_PROMPT_POLICIES)}"
            )
        if source["commit_policy"] not in COMMIT_POLICIES:
            raise ValueError(
                f"source {name}: commit_policy must be one of {sorted(COMMIT_POLICIES)}"
            )


def load_curated_samples(path: Path) -> list[dict[str, Any]]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    samples = payload.get("samples")
    if not isinstance(samples, list):
        raise ValueError("samples must be a list")
    validated: list[dict[str, Any]] = []
    for index, sample in enumerate(samples):
        if not isinstance(sample, dict):
            raise ValueError(f"sample #{index} must be an object")
        if sample.get("slice") not in KNOWN_SLICES:
            raise ValueError(f"sample #{index}: unknown slice {sample.get('slice')!r}")
        if sample.get("expect") not in KNOWN_ROUTES:
            raise ValueError(f"sample #{index}: expect must be lite or deep")
        allowed_routes = EXPECTED_ROUTES_BY_SLICE[str(sample["slice"])]
        if sample["expect"] not in allowed_routes:
            raise ValueError(
                f"sample #{index}: expected route for {sample['slice']} must be "
                f"one of {sorted(allowed_routes)}"
            )
        if sample.get("redacted") is not True:
            raise ValueError(f"sample #{index}: redacted must be true")
        for key in ("id", "text", "source", "rationale"):
            if not isinstance(sample.get(key), str) or not sample[key]:
                raise ValueError(f"sample #{index}: missing {key}")
        if (
            sample.get("slice") == "borderline_zh"
            and sample.get("label_policy") != "manual_review_required"
        ):
            raise ValueError(
                f"sample #{index}: borderline_zh requires manual_review_required"
            )
        if sample["slice"] == "deep_long_context_zh":
            validate_long_context_metadata(sample, index)
        validated.append(dict(sample))
    return validated


def validate_long_context_metadata(sample: dict[str, Any], index: int) -> None:
    context_policy = sample.get("context_policy")
    if context_policy not in LONG_CONTEXT_POLICIES:
        raise ValueError(
            f"sample #{index}: deep_long_context_zh requires context_policy"
        )
    if context_policy == "preserved_length":
        if not isinstance(sample.get("input_chars"), int) or sample["input_chars"] <= 0:
            raise ValueError(
                f"sample #{index}: preserved_length requires positive input_chars"
            )
        if (
            not isinstance(sample.get("message_count"), int)
            or sample["message_count"] <= 0
        ):
            raise ValueError(
                f"sample #{index}: preserved_length requires positive message_count"
            )


def build_eval_payload(samples: list[dict[str, Any]]) -> dict[str, Any]:
    seen_ids: set[str] = set()
    cases: list[dict[str, Any]] = []
    for sample in samples:
        sample_id = sample["id"]
        if sample_id in seen_ids:
            raise ValueError(f"duplicate case id: {sample_id}")
        seen_ids.add(sample_id)
        case = {
            "id": sample_id,
            "slice": sample["slice"],
            "text": sample["text"],
            "expect": sample["expect"],
            "source": sample["source"],
            "rationale": sample["rationale"],
        }
        for key in ("input_chars", "message_count", "context_policy"):
            if key in sample:
                case[key] = sample[key]
        cases.append(case)
    return {
        "schema": "zh-intentmux-router-eval-v1",
        "cases": cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--curated-samples", action="append", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    samples: list[dict[str, Any]] = []
    for path in args.curated_samples:
        samples.extend(load_curated_samples(Path(path)))
    payload = build_eval_payload(samples)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print(f"wrote {output} with {len(payload['cases'])} cases")


if __name__ == "__main__":
    main()
