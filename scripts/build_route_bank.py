from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class SourceMapping:
    field: str
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RouteSource:
    name: str
    kind: str
    route: str
    text_field: str
    limit: int
    path: str | None = None
    dataset: str | None = None
    subset: str | None = None
    split: str | None = None
    mappings: list[SourceMapping] = field(default_factory=list)


def normalize_text(text: str, max_chars: int = 240) -> str:
    return re.sub(r"\s+", " ", text).strip()[:max_chars]


def build_route_bank(
    sources: list[RouteSource],
    source_rows: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    routes: dict[str, dict[str, list[dict[str, str]]]] = {}
    for source in sources:
        selected: list[dict[str, str]] = []
        for row in source_rows.get(source.name, []):
            if not row_matches(row, source.mappings):
                continue
            text = normalize_text(str(row.get(source.text_field, "")))
            if not text:
                continue
            selected.append({"text": text, "source": source.name})
            if len(selected) >= source.limit:
                break

        route_bank = routes.setdefault(source.route, {"utterances": []})
        route_bank["utterances"].extend(selected)

    return {
        "version": 1,
        "routes": routes,
    }


def row_matches(row: dict[str, Any], mappings: list[SourceMapping]) -> bool:
    for mapping in mappings:
        value = str(row.get(mapping.field, ""))
        if mapping.include and value not in mapping.include:
            return False
        if mapping.exclude and value in mapping.exclude:
            return False
    return True


def load_sources(path: Path) -> list[RouteSource]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [
        RouteSource(
            name=item["name"],
            kind=item["kind"],
            route=item["route"],
            text_field=item["text_field"],
            limit=int(item.get("limit", 100)),
            path=item.get("path"),
            dataset=item.get("dataset"),
            subset=item.get("subset"),
            split=item.get("split"),
            mappings=[
                SourceMapping(
                    field=mapping["field"],
                    include=list(mapping.get("include", [])),
                    exclude=list(mapping.get("exclude", [])),
                )
                for mapping in item.get("mappings", [])
            ],
        )
        for item in raw["sources"]
    ]


def load_rows(source: RouteSource, base_dir: Path) -> list[dict[str, Any]]:
    if source.kind == "local_jsonl":
        if source.path is None:
            raise ValueError(f"{source.name} local_jsonl source requires path")
        rows = []
        path = base_dir / source.path
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                if line.strip():
                    rows.append(json.loads(line))
        return rows

    if source.kind == "huggingface":
        try:
            from datasets import load_dataset
        except ImportError as exc:
            raise RuntimeError(
                "Hugging Face sources require `uv sync --group assets`."
            ) from exc
        dataset_args = [source.dataset]
        if source.subset:
            dataset_args.append(source.subset)
        dataset = load_dataset(*dataset_args, split=source.split or "train")
        return [dict(row) for row in dataset]

    if source.kind == "local_rows":
        return []

    raise ValueError(f"unsupported source kind: {source.kind}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", default="config/route_sources.yaml")
    parser.add_argument("--output", default="data/semantic_sets/route_bank.yaml")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    sources = load_sources(repo_root / args.sources)
    rows = {source.name: load_rows(source, repo_root) for source in sources}
    bank = build_route_bank(sources, rows)

    output_path = repo_root / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        yaml.safe_dump(bank, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print(f"wrote {output_path}")


if __name__ == "__main__":
    main()

