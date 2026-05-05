from __future__ import annotations

import argparse
import json
from pathlib import Path
from collections import Counter
from typing import Any, Iterable

import yaml


class ReviewSampleError(ValueError):
    pass


def load_route_ids(path: Path) -> set[str]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    routes = raw.get("routes") if isinstance(raw, dict) else None
    if not isinstance(routes, dict):
        raise ReviewSampleError("routes config must define a routes mapping")
    return set(routes)


def convert_review_samples(
    lines: Iterable[str],
    *,
    allowed_route_ids: set[str] | None = None,
) -> dict[str, list[dict[str, str]]]:
    converted = convert_review_samples_with_summary(lines, allowed_route_ids=allowed_route_ids)
    return {"cases": converted["cases"]}


def convert_review_samples_with_summary(
    lines: Iterable[str],
    *,
    allowed_route_ids: set[str] | None = None,
) -> dict[str, Any]:
    cases: list[dict[str, str]] = []
    seen: set[str] = set()
    route_counts: Counter[str] = Counter()
    input_line_count = 0
    duplicate_text_count = 0
    skipped_blank_line_count = 0
    for line_number, line in enumerate(lines, start=1):
        input_line_count += 1
        line = line.strip()
        if not line:
            skipped_blank_line_count += 1
            continue
        try:
            sample = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ReviewSampleError(f"line {line_number}: invalid json") from exc
        case = review_sample_to_case(
            sample,
            line_number=line_number,
            allowed_route_ids=allowed_route_ids,
        )
        if case["text"] in seen:
            duplicate_text_count += 1
            continue
        cases.append(case)
        seen.add(case["text"])
        route_counts[case["expect"]] += 1
    summary = {
        "input_line_count": input_line_count,
        "accepted_case_count": len(cases),
        "duplicate_text_count": duplicate_text_count,
        "skipped_blank_line_count": skipped_blank_line_count,
        "route_counts": dict(route_counts),
    }
    return {"cases": cases, "summary": summary}


def format_text_summary(summary: dict[str, Any]) -> str:
    route_counts = summary.get("route_counts", {})
    routes = ", ".join(f"{route}={count}" for route, count in sorted(route_counts.items())) or "none"
    return (
        "summary: "
        f"input_lines={summary['input_line_count']} "
        f"accepted_cases={summary['accepted_case_count']} "
        f"duplicates={summary['duplicate_text_count']} "
        f"blank_lines={summary['skipped_blank_line_count']} "
        f"routes=[{routes}]"
    )


def review_sample_to_case(
    sample: dict[str, Any],
    *,
    line_number: int,
    allowed_route_ids: set[str] | None = None,
) -> dict[str, str]:
    if sample.get("redacted") is not True:
        raise ReviewSampleError(f"line {line_number}: review sample must set redacted=true")

    text = sample.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ReviewSampleError(f"line {line_number}: text must be a non-empty string")

    expect = sample.get("expect")
    if not isinstance(expect, str) or not expect.strip():
        raise ReviewSampleError(f"line {line_number}: expect must be a non-empty route_id")
    expect = expect.strip()
    if allowed_route_ids is not None and expect not in allowed_route_ids:
        raise ReviewSampleError(f"line {line_number}: expect route_id '{expect}' not found in routes config")

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
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--summary-json", action="store_true")
    parser.add_argument("--output-summary", choices=("text", "json"), default="text")
    parser.add_argument("--routes")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    allowed_route_ids = load_route_ids(Path(args.routes)) if args.routes else None
    result = convert_review_samples_with_summary(
        input_path.read_text(encoding="utf-8").splitlines(),
        allowed_route_ids=allowed_route_ids,
    )
    summary = dict(result["summary"])

    if not args.dry_run:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            yaml.safe_dump({"cases": result["cases"]}, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        summary["output_path"] = str(output_path)
        print(f"wrote {output_path} with {len(result['cases'])} review cases")

    output_summary = "json" if args.summary_json else args.output_summary
    if args.dry_run or output_summary == "json":
        if output_summary == "json":
            print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        else:
            print(format_text_summary(summary))


if __name__ == "__main__":
    main()
