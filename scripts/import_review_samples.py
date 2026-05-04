from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

import yaml


ALLOWED_ROUTES = {"cheap-router", "pro-router", "free-probe-router"}


class ReviewSampleError(ValueError):
    pass


def convert_review_samples(lines: Iterable[str]) -> dict[str, list[dict[str, str]]]:
    cases: list[dict[str, str]] = []
    seen: set[str] = set()
    for line_number, line in enumerate(lines, start=1):
        line = line.strip()
        if not line:
            continue
        try:
            sample = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ReviewSampleError(f"line {line_number}: invalid json") from exc
        case = review_sample_to_case(sample, line_number=line_number)
        if case["text"] in seen:
            continue
        cases.append(case)
        seen.add(case["text"])
    return {"cases": cases}


def review_sample_to_case(sample: dict[str, Any], *, line_number: int) -> dict[str, str]:
    if sample.get("redacted") is not True:
        raise ReviewSampleError(f"line {line_number}: review sample must set redacted=true")

    text = sample.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ReviewSampleError(f"line {line_number}: text must be a non-empty string")

    expect = sample.get("expect")
    if expect not in ALLOWED_ROUTES:
        raise ReviewSampleError(f"line {line_number}: unknown expect route {expect!r}")

    source = sample.get("source")
    case_source = "production_review"
    if isinstance(source, str) and source.strip():
        case_source = f"production_review:{source.strip()}"

    case = {
        "text": text,
        "expect": expect,
        "source": case_source,
    }
    note = sample.get("note")
    if isinstance(note, str) and note.strip():
        case["note"] = note
    return case


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert redacted production review JSONL into eval case YAML.",
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    result = convert_review_samples(input_path.read_text(encoding="utf-8").splitlines())
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        yaml.safe_dump(result, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print(f"wrote {output_path} with {len(result['cases'])} review cases")


if __name__ == "__main__":
    main()
