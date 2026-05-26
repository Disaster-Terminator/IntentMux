from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
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


def check_cloud_runtime(runtime_home: Path) -> list[CheckResult]:
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
    args = parser.parse_args(argv)
    results = check_cloud_runtime(args.runtime_home)
    for result in results:
        status = "PASS" if result.ok else "FAIL"
        print(f"{status}\t{result.name}\t{result.detail}")
    if not all(result.ok for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
