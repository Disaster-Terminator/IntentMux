from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml


FORBIDDEN_ARTIFACT_PATTERNS = (
    ".env",
    "**/.env",
    "*.env",
    "**/*.env",
    "logs/prompts/*.jsonl",
    "logs/quality/**",
    "logs/**/*",
    "reports/**",
    "reviews/**",
    "config/*.bak",
    "config/*.backup*",
    "config/*.old",
    "config/routes.yaml.*",
    "*.stdout",
    "**/*.stdout",
    "**/*.tmp",
    "**/*.swp",
    ".git/**/*",
    "**/.git/**/*",
    "**/.DS_Store",
    "**/__pycache__/**/*",
    "pids/**/*",
    "secrets/**/*",
    "private/**/*",
    "state/**/*",
)
LOCAL_ONLY_PATTERNS = (
    re.compile(r"\b127\.0\.0\.1\b"),
    re.compile(r"\blocalhost\b", re.IGNORECASE),
    re.compile(r"\bhost\.docker\.internal\b", re.IGNORECASE),
    re.compile(r"/home/[A-Za-z0-9._-]+/"),
    re.compile(r"[A-Za-z]:\\"),
)
SECRET_LIKE_PATTERNS = (
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\b[A-Z0-9_]*(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD)\s*[:=]\s*\S{8,}", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bark-[A-Za-z0-9-]{20,}"),
    re.compile(r"\bms-[A-Za-z0-9_-]{8,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{20,}"),
    re.compile(r"\bA[KS]IA[0-9A-Z]{16}\b"),
)
TEXT_SCAN_SUFFIXES = {".env", ".json", ".jsonl", ".md", ".txt", ".yaml", ".yml"}


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


def check_cloud_runtime(
    runtime_home: Path,
    *,
    require_route_cache: bool = False,
    expected_embedding_model: str | None = None,
    expected_embedding_input_max_chars: int | None = None,
) -> list[CheckResult]:
    runtime_home = runtime_home.expanduser()
    config_path = runtime_home / "config" / "routes.yaml"
    raw_config = load_config(config_path)
    route_bank_path = resolve_route_bank_path(runtime_home, config_path, raw_config)
    forbidden_paths = forbidden_artifact_paths(runtime_home)
    results = [
        CheckResult(
            "runtime_home",
            runtime_home.is_dir(),
            str(runtime_home),
        ),
        CheckResult(
            "routes_config",
            config_path.is_file(),
            relative_detail(config_path, runtime_home),
        ),
        CheckResult(
            "route_bank",
            route_bank_path.is_file(),
            relative_detail(route_bank_path, runtime_home),
        ),
    ]
    results.append(route_bank_inside_runtime_result(route_bank_path, runtime_home))
    results.append(unsafe_symlinks_result(runtime_home))
    results.append(forbidden_artifacts_result(runtime_home, forbidden_paths))
    results.append(local_only_hosts_result(runtime_home, forbidden_paths))
    results.append(secret_like_values_result(runtime_home, forbidden_paths))
    if raw_config is not None:
        results.append(placeholder_targets_result(raw_config))
        results.append(recursive_route_config_result(raw_config))
        results.append(cloudflare_embedding_endpoint_result(raw_config))
        results.append(
            route_embedding_cache_result(
                runtime_home,
                config_path,
                raw_config,
                route_bank_path,
                require_route_cache=require_route_cache,
                expected_embedding_model=expected_embedding_model,
                expected_embedding_input_max_chars=expected_embedding_input_max_chars,
            )
        )
    return results


def load_config(config_path: Path) -> dict | None:
    if not config_path.is_file():
        return None
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return {}
    return raw


def resolve_route_bank_path(runtime_home: Path, config_path: Path, raw_config: dict | None) -> Path:
    configured_path = raw_config.get("route_bank_path") if raw_config else None
    if isinstance(configured_path, str) and configured_path:
        path = Path(configured_path).expanduser()
        if path.is_absolute():
            return path
        return (config_path.parent / path).resolve()
    return runtime_home / "semantic_sets" / "route_bank.yaml"


def resolve_route_embedding_cache_path(
    runtime_home: Path,
    config_path: Path,
    raw_config: dict,
) -> Path:
    configured_path = raw_config.get("route_embedding_cache_path")
    if isinstance(configured_path, str) and configured_path:
        path = Path(configured_path).expanduser()
        if path.is_absolute():
            return path
        return (config_path.parent / path).resolve()
    return runtime_home / "cache" / "route-embeddings.json"


def route_embedding_cache_result(
    runtime_home: Path,
    config_path: Path,
    raw_config: dict,
    route_bank_path: Path,
    *,
    require_route_cache: bool,
    expected_embedding_model: str | None,
    expected_embedding_input_max_chars: int | None,
) -> CheckResult:
    enabled = bool_from_value(raw_config.get("route_embedding_cache_enabled", True))
    cache_path = resolve_route_embedding_cache_path(runtime_home, config_path, raw_config)
    if not enabled:
        return CheckResult(
            "route_embedding_cache",
            not require_route_cache,
            "disabled",
        )
    if not cache_path.is_file():
        return CheckResult(
            "route_embedding_cache",
            not require_route_cache,
            f"{'missing' if require_route_cache else 'optional_missing'}:{relative_detail(cache_path, runtime_home)}",
        )
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return CheckResult(
            "route_embedding_cache",
            False,
            f"unreadable:{type(exc).__name__}:{relative_detail(cache_path, runtime_home)}",
        )
    issues = route_embedding_cache_issues(
        payload,
        raw_config,
        route_bank_path,
        expected_embedding_model=expected_embedding_model,
        expected_embedding_input_max_chars=expected_embedding_input_max_chars,
    )
    return CheckResult(
        "route_embedding_cache",
        not issues,
        f"ok:{relative_detail(cache_path, runtime_home)}" if not issues else ",".join(issues[:20]),
    )


def route_embedding_cache_issues(
    payload: Any,
    raw_config: dict,
    route_bank_path: Path,
    *,
    expected_embedding_model: str | None,
    expected_embedding_input_max_chars: int | None,
) -> list[str]:
    if not isinstance(payload, dict):
        return ["payload_not_object"]
    issues: list[str] = []
    if payload.get("version") != 1:
        issues.append(f"version:{payload.get('version')}")
    if (
        expected_embedding_model
        and payload.get("embedding_model") != expected_embedding_model
    ):
        issues.append("embedding_model_mismatch")
    if (
        expected_embedding_input_max_chars is not None
        and payload.get("embedding_input_max_chars") != expected_embedding_input_max_chars
    ):
        issues.append("embedding_input_max_chars_mismatch")

    entries = route_corpus_entries(raw_config, route_bank_path)
    expected_fingerprint = route_bank_fingerprint(entries)
    if payload.get("route_bank_sha256") != expected_fingerprint:
        issues.append("route_bank_sha256_mismatch")

    items = payload.get("items")
    if not isinstance(items, list):
        issues.append("items_not_list")
        return issues
    if len(items) != len(entries):
        issues.append(f"items_count:{len(items)}!=expected:{len(entries)}")
        return issues
    for index, (entry, item) in enumerate(zip(entries, items)):
        if not isinstance(item, dict):
            issues.append(f"item_not_object:{index}")
            break
        vector = item.get("vector")
        if (
            item.get("route_id") != entry["route_id"]
            or item.get("source") != entry["source"]
            or item.get("index") != entry["index"]
            or item.get("text_sha256") != entry["text_sha256"]
            or not isinstance(vector, list)
        ):
            issues.append(f"item_mismatch:{index}")
            break
    return issues


def route_corpus_entries(raw_config: dict, route_bank_path: Path) -> list[dict[str, Any]]:
    routes = raw_config.get("routes") or {}
    if not isinstance(routes, dict):
        return []
    merged_routes = {
        route_id: dict(route_config)
        for route_id, route_config in routes.items()
        if isinstance(route_config, dict)
    }
    merge_route_bank_utterances(merged_routes, route_bank_path)
    entries: list[dict[str, Any]] = []
    for route_id, route_config in merged_routes.items():
        utterances = route_config.get("utterances") or []
        sources = route_config.get("utterance_sources") or {}
        if not isinstance(utterances, list):
            continue
        if not isinstance(sources, dict):
            sources = {}
        for index, text in enumerate(utterances):
            if not isinstance(text, str):
                continue
            entries.append(
                {
                    "route_id": route_id,
                    "text": text,
                    "source": sources.get(text) or "inline_config",
                    "index": index,
                    "text_sha256": sha256_text(text),
                }
            )
    return entries


def merge_route_bank_utterances(
    routes: dict[str, dict[str, Any]],
    route_bank_path: Path,
) -> None:
    if not route_bank_path.is_file():
        return
    raw_bank = yaml.safe_load(route_bank_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw_bank, dict):
        return
    bank_routes = raw_bank.get("routes") or {}
    if not isinstance(bank_routes, dict):
        return
    for route_id, route_bank in bank_routes.items():
        if route_id not in routes or not isinstance(route_bank, dict):
            continue
        route_config = routes[route_id]
        utterances = list(route_config.get("utterances") or [])
        sources = dict(route_config.get("utterance_sources") or {})
        seen = set(utterances)
        for item in route_bank.get("utterances", []):
            text = item.get("text") if isinstance(item, dict) else item
            if not isinstance(text, str) or not text:
                continue
            if text not in seen:
                utterances.append(text)
                seen.add(text)
            if isinstance(item, dict) and isinstance(item.get("source"), str):
                sources[text] = item["source"]
        route_config["utterances"] = utterances
        route_config["utterance_sources"] = sources


def route_bank_fingerprint(entries: list[dict[str, Any]]) -> str:
    lines = [
        json.dumps(
            {
                "route_id": entry["route_id"],
                "source": entry["source"],
                "index": entry["index"],
                "text_sha256": entry["text_sha256"],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for entry in entries
    ]
    return sha256_text("\n".join(lines))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def route_bank_inside_runtime_result(route_bank_path: Path, runtime_home: Path) -> CheckResult:
    try:
        route_bank_path.resolve(strict=False).relative_to(runtime_home.resolve(strict=False))
    except ValueError:
        return CheckResult(
            "route_bank_inside_runtime",
            False,
            str(route_bank_path),
        )
    return CheckResult(
        "route_bank_inside_runtime",
        True,
        relative_detail(route_bank_path, runtime_home),
    )


def unsafe_symlinks_result(runtime_home: Path) -> CheckResult:
    root = runtime_home.resolve(strict=False)
    matches: list[str] = []
    for path in runtime_home.rglob("*"):
        if not path.is_symlink():
            continue
        try:
            path.resolve(strict=False).relative_to(root)
        except ValueError:
            matches.append(relative_detail(path, runtime_home))
    matches = sorted(matches)
    return CheckResult(
        "unsafe_symlinks",
        not matches,
        "none" if not matches else ",".join(matches[:20]),
    )


def forbidden_artifact_paths(runtime_home: Path) -> set[Path]:
    matches: set[Path] = set()
    for pattern in FORBIDDEN_ARTIFACT_PATTERNS:
        for path in runtime_home.glob(pattern):
            if path.is_file() or path.is_symlink():
                matches.add(path)
    return matches


def forbidden_artifacts_result(runtime_home: Path, paths: set[Path]) -> CheckResult:
    matches = sorted({relative_detail(path, runtime_home) for path in paths})
    return CheckResult(
        "forbidden_runtime_artifacts",
        not matches,
        "none" if not matches else ",".join(matches[:20]),
    )


def local_only_hosts_result(runtime_home: Path, forbidden_paths: set[Path]) -> CheckResult:
    matches = sorted(
        {
            f"{relative_detail(path, runtime_home)}:{line_no}:{match.group(0)}"
            for path, line_no, line in iter_config_lines(runtime_home, forbidden_paths)
            for pattern in LOCAL_ONLY_PATTERNS
            for match in pattern.finditer(line)
        }
    )
    return CheckResult(
        "local_only_hosts",
        not matches,
        "none" if not matches else ",".join(matches[:20]),
    )


def secret_like_values_result(runtime_home: Path, forbidden_paths: set[Path]) -> CheckResult:
    matches = sorted(
        {
            f"{relative_detail(path, runtime_home)}:{line_no}"
            for path, line_no, line in iter_scannable_lines(runtime_home, forbidden_paths)
            if any(pattern.search(line) for pattern in SECRET_LIKE_PATTERNS)
        }
    )
    return CheckResult(
        "secret_like_values",
        not matches,
        "none" if not matches else ",".join(matches[:20]),
    )


def iter_scannable_lines(
    runtime_home: Path,
    forbidden_paths: set[Path],
) -> list[tuple[Path, int, str]]:
    lines: list[tuple[Path, int, str]] = []
    for path in sorted(runtime_home.rglob("*")):
        if path in forbidden_paths or path.is_symlink() or not path.is_file():
            continue
        if path.name != ".env" and path.suffix.lower() not in TEXT_SCAN_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        lines.extend((path, line_no, line) for line_no, line in enumerate(text.splitlines(), start=1))
    return lines


def iter_config_lines(
    runtime_home: Path,
    forbidden_paths: set[Path],
) -> list[tuple[Path, int, str]]:
    config_dir = runtime_home / "config"
    if not config_dir.is_dir():
        return []
    return [
        item
        for item in iter_scannable_lines(config_dir, {path for path in forbidden_paths if path.is_relative_to(config_dir)})
    ]


def placeholder_targets_result(raw: dict) -> CheckResult:
    routes = raw.get("routes") or {}
    placeholders = []
    if isinstance(routes, dict):
        for route_id, route in routes.items():
            if not isinstance(route, dict):
                continue
            target_model = route.get("target_model")
            if isinstance(target_model, str) and target_model.startswith("your-"):
                placeholders.append(f"{route_id}:{target_model}")
    return CheckResult(
        "placeholder_target_models",
        not placeholders,
        "none" if not placeholders else ",".join(placeholders),
    )


def recursive_route_config_result(raw: dict) -> CheckResult:
    route_model = raw.get("route_model", raw.get("entry_model", "intentmux"))
    routes = raw.get("routes") or {}
    issues: list[str] = []
    if isinstance(route_model, str) and isinstance(routes, dict):
        if route_model in routes:
            issues.append(f"route_model_is_route_id:{route_model}")
        for route_id, route in routes.items():
            if not isinstance(route, dict):
                continue
            target_model = route.get("target_model", route_id)
            if target_model == route_model:
                issues.append(f"{route_id}:target_model={target_model}")
    return CheckResult(
        "recursive_route_config",
        not issues,
        "none" if not issues else ",".join(issues),
    )


def cloudflare_embedding_endpoint_result(raw: dict) -> CheckResult:
    embedding_url = raw.get("embedding_url")
    if not isinstance(embedding_url, str) or not embedding_url:
        return CheckResult("cloudflare_embedding_endpoint", True, "not_cloudflare")
    parsed = urlparse(embedding_url)
    if parsed.netloc != "api.cloudflare.com":
        return CheckResult("cloudflare_embedding_endpoint", True, "not_cloudflare")
    if "/ai/run/" in parsed.path:
        return CheckResult(
            "cloudflare_embedding_endpoint",
            False,
            "native_ai_run_endpoint_not_openai_compatible",
        )
    ok = parsed.path.endswith("/ai/v1/embeddings")
    return CheckResult(
        "cloudflare_embedding_endpoint",
        ok,
        "openai_compatible" if ok else f"unexpected_path:{parsed.path}",
    )


def bool_from_value(value: Any) -> bool:
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def optional_int(value: str | None) -> int | None:
    if value is None:
        return None
    if value.strip().lower() in {"", "none", "null"}:
        return None
    return int(value)


def relative_detail(path: Path, runtime_home: Path) -> str:
    try:
        return path.relative_to(runtime_home).as_posix()
    except ValueError:
        try:
            return path.resolve(strict=False).relative_to(runtime_home.resolve(strict=False)).as_posix()
        except ValueError:
            return str(path)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("runtime_home", type=Path)
    parser.add_argument(
        "--require-route-cache",
        action="store_true",
        help="Fail when the route embedding cache is disabled or missing.",
    )
    parser.add_argument(
        "--expected-embedding-model",
        help="Expected embedding_model metadata for cache validation.",
    )
    parser.add_argument(
        "--expected-embedding-input-max-chars",
        type=optional_int,
        help="Expected embedding_input_max_chars metadata for cache validation.",
    )
    args = parser.parse_args(argv)
    results = check_cloud_runtime(
        args.runtime_home,
        require_route_cache=args.require_route_cache,
        expected_embedding_model=args.expected_embedding_model,
        expected_embedding_input_max_chars=args.expected_embedding_input_max_chars,
    )
    for result in results:
        status = "PASS" if result.ok else "FAIL"
        print(f"{status}\t{result.name}\t{result.detail}")
    if not all(result.ok for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
