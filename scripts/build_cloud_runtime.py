#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.check_cloud_runtime import CheckResult, check_cloud_runtime, resolve_route_bank_path  # noqa: E402


def build_cloud_runtime(
    source_runtime: Path,
    output_runtime: Path,
    *,
    litellm_base_url: str | None = None,
    embedding_url: str | None = None,
    include_route_cache: bool = False,
    force: bool = False,
) -> list[CheckResult]:
    source_runtime = source_runtime.expanduser().resolve()
    output_runtime = output_runtime.expanduser().resolve()
    config_path = source_runtime / "config" / "routes.yaml"
    if output_runtime == source_runtime or output_runtime.is_relative_to(source_runtime):
        raise ValueError("output runtime must not be the source runtime or inside it")
    if not config_path.is_file():
        raise ValueError(f"source routes config not found: {config_path}")

    raw_config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw_config, dict):
        raise ValueError("source routes config must be a YAML mapping")

    route_bank_path = resolve_route_bank_path(source_runtime, config_path, raw_config)
    if not route_bank_path.is_file():
        raise ValueError(f"source route bank not found: {route_bank_path}")

    prepare_output_dir(output_runtime, force=force)

    output_config = dict(raw_config)
    if litellm_base_url is not None:
        output_config["litellm_base_url"] = litellm_base_url
    if embedding_url is not None:
        output_config["embedding_url"] = embedding_url
    output_config["listen_host"] = "0.0.0.0"
    output_config["route_bank_path"] = "../semantic_sets/route_bank.yaml"

    (output_runtime / "config").mkdir(parents=True)
    (output_runtime / "semantic_sets").mkdir(parents=True)
    (output_runtime / "config" / "routes.yaml").write_text(
        yaml.safe_dump(output_config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    shutil.copy2(route_bank_path, output_runtime / "semantic_sets" / "route_bank.yaml")
    if include_route_cache:
        route_cache_path = resolve_route_embedding_cache_path(
            source_runtime,
            config_path,
            raw_config,
        )
        if not route_cache_path.is_file():
            raise ValueError(f"source route embedding cache not found: {route_cache_path}")
        (output_runtime / "cache").mkdir(parents=True)
        shutil.copy2(route_cache_path, output_runtime / "cache" / "route-embeddings.json")
    return check_cloud_runtime(output_runtime)


def prepare_output_dir(output_runtime: Path, *, force: bool) -> None:
    if output_runtime.exists():
        if not output_runtime.is_dir():
            raise ValueError(f"output runtime exists but is not a directory: {output_runtime}")
        if any(output_runtime.iterdir()):
            if not force:
                raise ValueError(f"output runtime is not empty: {output_runtime}")
            shutil.rmtree(output_runtime)
    output_runtime.mkdir(parents=True, exist_ok=True)


def resolve_route_embedding_cache_path(
    source_runtime: Path,
    config_path: Path,
    raw_config: dict,
) -> Path:
    configured_path = raw_config.get("route_embedding_cache_path")
    if isinstance(configured_path, str) and configured_path:
        path = Path(configured_path).expanduser()
        if path.is_absolute():
            return path
        return (config_path.parent / path).resolve()
    return source_runtime / "cache" / "route-embeddings.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a sanitized IntentMux runtime directory for hosted deployments."
    )
    parser.add_argument("--source-runtime", type=Path, required=True)
    parser.add_argument("--output-runtime", type=Path, required=True)
    parser.add_argument("--litellm-base-url")
    parser.add_argument("--embedding-url")
    parser.add_argument(
        "--include-route-cache",
        action="store_true",
        help="Copy cache/route-embeddings.json into the cloud runtime bundle.",
    )
    parser.add_argument("--force", action="store_true", help="Replace a non-empty output directory.")
    args = parser.parse_args(argv)

    results = build_cloud_runtime(
        args.source_runtime,
        args.output_runtime,
        litellm_base_url=args.litellm_base_url,
        embedding_url=args.embedding_url,
        include_route_cache=args.include_route_cache,
        force=args.force,
    )
    for result in results:
        status = "PASS" if result.ok else "FAIL"
        print(f"{status}\t{result.name}\t{result.detail}")
    if not all(result.ok for result in results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
