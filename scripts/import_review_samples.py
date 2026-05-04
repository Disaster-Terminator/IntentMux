from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

import yaml


ALLOWED_ROUTES = {"cheap-router", "pro-router", "free-probe-router"}


class ReviewSampleError(ValueError):
    pass


def convert_review_samples(
    lines: Iterable[str],
) -> tuple[dict[str, list[dict[str, str]]], dict[str, Any]]:
    cases: list[dict[str, str]] = []
    seen: set[str] = set()
    summary: dict[str, Any] = {
        "input_line_count": 0,
        "accepted_case_count": 0,
        "duplicate_text_count": 0,
        "skipped_blank_line_count": 0,
        "route_counts": {route: 0 for route in sorted(ALLOWED_ROUTES)},
    }

    for line_number, line in enumerate(lines, start=1):
        summary["input_line_count"] += 1
        line = line.strip()
        if not line:
            summary["skipped_blank_line_count"] += 1
            continue
        try:
            sample = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ReviewSampleError(f"line {line_number}: invalid json") from exc
        case = review_sample_to_case(sample, line_number=line_number)
        if case["text"] in seen:
            summary["duplicate_text_count"] += 1
            continue
        cases.append(case)
        seen.add(case["text"])
        summary["accepted_case_count"] += 1
        summary["route_counts"][case["expect"]] += 1

    return {"cases": cases}, summary


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


def _print_summary(summary: dict[str, Any]) -> None:
    print("summary:")
    print(f"  input_line_count: {summary['input_line_count']}")
    print(f"  accepted_case_count: {summary['accepted_case_count']}")
    print(f"  duplicate_text_count: {summary['duplicate_text_count']}")
    print(f"  skipped_blank_line_count: {summary['skipped_blank_line_count']}")
    if "output_path" in summary:
        print(f"  output_path: {summary['output_path']}")
    print("  route_counts:")
    for route, count in summary["route_counts"].items():
        print(f"    {route}: {count}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert redacted production review JSONL into eval case YAML.",
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--summary-json", action="store_true")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    result, summary = convert_review_samples(input_path.read_text(encoding="utf-8").splitlines())

    if not args.dry_run:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            yaml.safe_dump(result, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        summary["output_path"] = str(output_path)
        print(f"wrote {output_path} with {len(result['cases'])} review cases")

    if args.summary_json:
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    else:
        _print_summary(summary)


if __name__ == "__main__":
    main()
