from __future__ import annotations

import argparse
import json
import re
import tarfile
import urllib.request
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
    url: str | None = None
    member: str | None = None
    dataset: str | None = None
    subset: str | None = None
    split: str | None = None
    homepage: str | None = None
    license: str | None = None
    license_url: str | None = None
    mappings: list[SourceMapping] = field(default_factory=list)


def normalize_text(text: str, max_chars: int = 240) -> str:
    without_comments = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    without_markdown_headings = re.sub(
        r"^\s*#+\s*", "", without_comments, flags=re.MULTILINE
    )
    return re.sub(r"\s+", " ", without_markdown_headings).strip()[:max_chars]


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
        "sources": [source_metadata(source) for source in sources],
        "routes": routes,
    }


def source_metadata(source: RouteSource) -> dict[str, str | int | None]:
    return {
        "name": source.name,
        "kind": source.kind,
        "route": source.route,
        "limit": source.limit,
        "url": source.url,
        "dataset": source.dataset,
        "split": source.split,
        "homepage": source.homepage,
        "license": source.license,
        "license_url": source.license_url,
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
            url=item.get("url"),
            member=item.get("member"),
            dataset=item.get("dataset"),
            subset=item.get("subset"),
            split=item.get("split"),
            homepage=item.get("homepage"),
            license=item.get("license"),
            license_url=item.get("license_url"),
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

    if source.kind == "remote_tar_jsonl":
        if source.url is None or source.member is None:
            raise ValueError(f"{source.name} remote_tar_jsonl source requires url and member")
        archive_path = cached_download(source.url, base_dir / "data" / "downloads")
        rows = []
        with tarfile.open(archive_path, "r:gz") as archive:
            member_file = archive.extractfile(source.member)
            if member_file is None:
                raise ValueError(f"{source.member} not found in {archive_path}")
            for raw_line in member_file:
                line = raw_line.decode("utf-8").strip()
                if line:
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


def cached_download(url: str, download_dir: Path) -> Path:
    download_dir.mkdir(parents=True, exist_ok=True)
    filename = url.rstrip("/").split("/")[-1]
    target = download_dir / filename
    if not target.exists():
        urllib.request.urlretrieve(url, target)
    return target


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
