from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

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
            raise ValueError(f"sample #{index}: expect must be fast or strong")
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
        validated.append(dict(sample))
    return validated


def build_eval_payload(samples: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": "zh-intentmux-router-eval-v1",
        "cases": [
            {
                "id": sample["id"],
                "slice": sample["slice"],
                "text": sample["text"],
                "expect": sample["expect"],
                "source": sample["source"],
                "rationale": sample["rationale"],
            }
            for sample in samples
        ],
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
