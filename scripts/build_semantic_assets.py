from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.build_route_bank import (
    RouteSource,
    load_rows,
    load_sources,
    normalize_text,
    row_matches,
)

ASSET_SCHEMA = "intentmux-semantic-assets-v2"
SUPPORTED_USES = {"route", "eval", "calibration"}


def build_normalized_records(
    sources: list[RouteSource],
    source_rows: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for source in sources:
        if source.intended_use not in SUPPORTED_USES:
            raise ValueError(
                f"{source.name}: intended_use must be one of {sorted(SUPPORTED_USES)}"
            )
        selected = 0
        for row in source_rows.get(source.name, []):
            if not row_matches(row, source.mappings):
                continue
            text = normalize_text(str(row.get(source.text_field, "")))
            if not text:
                continue
            record = {
                "id": normalized_record_id(source.name, text),
                "text": text,
                "source": source.name,
                "route_id": source.route,
                "language": source.language or "unknown",
                "slice": source.slice or "unsliced",
                "proposed_use": source.intended_use,
                "license": source.license or "unknown",
            }
            for key in ("input_chars", "message_count", "context_policy", "weight"):
                if key in row:
                    record[key] = row[key]
            records.append(record)
            selected += 1
            if selected >= source.limit:
                break
    return records


def normalized_record_id(source_name: str, text: str) -> str:
    digest = hashlib.sha256(f"{source_name}\0{text}".encode("utf-8")).hexdigest()[:16]
    return f"{source_name}:{digest}"


def build_route_bank_from_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    routes: dict[str, dict[str, list[dict[str, str]]]] = {}
    for record in records:
        if record["proposed_use"] != "route":
            continue
        route = routes.setdefault(record["route_id"], {"utterances": []})
        route["utterances"].append(
            {
                "text": record["text"],
                "source": record["source"],
                "id": record["id"],
                "slice": record["slice"],
                "language": record["language"],
            }
        )
    return {
        "version": 2,
        "schema": ASSET_SCHEMA,
        "routes": routes,
    }


def build_eval_bank_from_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": "intentmux-route-eval-v2",
        "cases": [
            eval_case_from_record(record)
            for record in records
            if record["proposed_use"] == "eval"
        ],
    }


def build_calibration_bank(records: list[dict[str, Any]]) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for record in records:
        if record["proposed_use"] != "calibration":
            continue
        case = eval_case_from_record(record)
        if "weight" in record:
            case["weight"] = record["weight"]
        cases.append(case)
    return {
        "schema": "intentmux-route-calibration-v1",
        "cases": cases,
    }


def eval_case_from_record(record: dict[str, Any]) -> dict[str, Any]:
    case = {
        "id": record["id"],
        "text": record["text"],
        "expect": record["route_id"],
        "source": record["source"],
        "slice": record["slice"],
        "language": record["language"],
    }
    for key in ("input_chars", "message_count", "context_policy"):
        if key in record:
            case[key] = record[key]
    return case


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )


def write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", default="config/route_sources.yaml")
    parser.add_argument(
        "--normalized-output",
        default="data/semantic_sets/normalized/semantic_records.jsonl",
    )
    parser.add_argument("--route-bank-output", default="data/semantic_sets/route_bank.yaml")
    parser.add_argument("--eval-bank-output", default="data/semantic_sets/eval_bank.yaml")
    parser.add_argument(
        "--calibration-bank-output",
        default="data/semantic_sets/calibration_bank.yaml",
    )
    args = parser.parse_args()

    sources_path = REPO_ROOT / args.sources
    sources = load_sources(sources_path)
    rows = {source.name: load_rows(source, REPO_ROOT) for source in sources}
    records = build_normalized_records(sources, rows)

    write_jsonl(REPO_ROOT / args.normalized_output, records)
    write_yaml(REPO_ROOT / args.route_bank_output, build_route_bank_from_records(records))
    write_yaml(REPO_ROOT / args.eval_bank_output, build_eval_bank_from_records(records))
    write_yaml(REPO_ROOT / args.calibration_bank_output, build_calibration_bank(records))

    print(
        "wrote "
        f"{args.normalized_output}, {args.route_bank_output}, "
        f"{args.eval_bank_output}, {args.calibration_bank_output}"
    )


if __name__ == "__main__":
    main()
