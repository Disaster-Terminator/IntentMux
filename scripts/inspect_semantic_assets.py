from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.build_route_bank import RouteSource, load_sources  # noqa: E402


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def count_by(records: list[dict[str, Any]], key: str) -> dict[str, int]:
    return dict(sorted(Counter(str(record.get(key, "unknown")) for record in records).items()))


def route_bank_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for route_id, route in (payload.get("routes") or {}).items():
        for utterance in route.get("utterances") or []:
            record = dict(utterance)
            record["route_id"] = str(route_id)
            records.append(record)
    return records


def eval_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(case) for case in payload.get("cases") or []]


def source_summary(sources: list[RouteSource]) -> list[dict[str, Any]]:
    return [
        {
            "name": source.name,
            "route": source.route,
            "use": source.intended_use,
            "language": source.language,
            "slice": source.slice,
            "limit": source.limit,
            "ingest_all": source.ingest_all,
        }
        for source in sources
    ]


def summarize_assets(
    sources_path: Path,
    normalized_path: Path,
    route_bank_path: Path,
    eval_bank_path: Path,
    calibration_bank_path: Path,
) -> dict[str, Any]:
    sources = load_sources(sources_path) if sources_path.exists() else []
    normalized = load_jsonl(normalized_path)
    route_bank = route_bank_records(load_yaml(route_bank_path))
    eval_bank = eval_records(load_yaml(eval_bank_path))
    calibration_bank = eval_records(load_yaml(calibration_bank_path))

    return {
        "sources_path": str(sources_path),
        "normalized_path": str(normalized_path),
        "route_bank_path": str(route_bank_path),
        "eval_bank_path": str(eval_bank_path),
        "calibration_bank_path": str(calibration_bank_path),
        "sources": source_summary(sources),
        "normalized": {
            "total": len(normalized),
            "by_use": count_by(normalized, "proposed_use"),
            "by_route": count_by(normalized, "route_id"),
            "by_source": count_by(normalized, "source"),
            "by_language": count_by(normalized, "language"),
        },
        "route_bank": {
            "total": len(route_bank),
            "by_route": count_by(route_bank, "route_id"),
            "by_source": count_by(route_bank, "source"),
            "by_language": count_by(route_bank, "language"),
            "by_slice": count_by(route_bank, "slice"),
        },
        "eval_bank": {
            "total": len(eval_bank),
            "by_route": count_by(eval_bank, "expect"),
            "by_source": count_by(eval_bank, "source"),
            "by_language": count_by(eval_bank, "language"),
        },
        "calibration_bank": {
            "total": len(calibration_bank),
            "by_route": count_by(calibration_bank, "expect"),
            "by_source": count_by(calibration_bank, "source"),
            "by_language": count_by(calibration_bank, "language"),
        },
    }


def format_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "none"
    return ", ".join(f"{key}={value}" for key, value in counts.items())


def render_text(summary: dict[str, Any]) -> str:
    lines = [
        "# IntentMux semantic assets",
        "",
        f"- normalized: {summary['normalized']['total']} ({format_counts(summary['normalized']['by_use'])})",
        f"- route_bank: {summary['route_bank']['total']} ({format_counts(summary['route_bank']['by_route'])})",
        f"- eval_bank: {summary['eval_bank']['total']} ({format_counts(summary['eval_bank']['by_route'])})",
        f"- calibration_bank: {summary['calibration_bank']['total']} ({format_counts(summary['calibration_bank']['by_route'])})",
        "",
        "## Route bank sources",
    ]
    for source, count in summary["route_bank"]["by_source"].items():
        lines.append(f"- {source}: {count}")
    lines.extend(
        [
            "",
            "## Route bank slices",
        ]
    )
    for slice_id, count in summary["route_bank"]["by_slice"].items():
        lines.append(f"- {slice_id}: {count}")
    lines.extend(
        [
            "",
            "## Configured route source limits",
        ]
    )
    for source in summary["sources"]:
        if source["use"] == "route":
            lines.append(
                "- "
                f"{source['name']}: route={source['route']} "
                f"language={source['language']} limit={source['limit']} "
                f"ingest_all={str(source['ingest_all']).lower()}"
            )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", default="config/route_sources.yaml")
    parser.add_argument(
        "--normalized",
        default="data/semantic_sets/normalized/semantic_records.jsonl",
    )
    parser.add_argument("--route-bank", default="data/semantic_sets/route_bank.yaml")
    parser.add_argument("--eval-bank", default="data/semantic_sets/eval_bank.yaml")
    parser.add_argument("--calibration-bank", default="data/semantic_sets/calibration_bank.yaml")
    parser.add_argument("--json", action="store_true", help="emit full JSON summary")
    args = parser.parse_args()

    summary = summarize_assets(
        REPO_ROOT / args.sources,
        REPO_ROOT / args.normalized,
        REPO_ROOT / args.route_bank,
        REPO_ROOT / args.eval_bank,
        REPO_ROOT / args.calibration_bank,
    )
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_text(summary), end="")


if __name__ == "__main__":
    main()
