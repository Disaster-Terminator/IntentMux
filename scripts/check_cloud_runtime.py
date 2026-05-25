from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

import yaml


FORBIDDEN_ARTIFACT_PATTERNS = (
    "logs/prompts/*.jsonl",
    "logs/quality/**",
    "reports/**",
    "reviews/**",
    "config/*.bak",
    "config/*.backup*",
    "config/*.old",
    "config/routes.yaml.*",
    "*.stdout",
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
)


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
    results.append(forbidden_artifacts_result(runtime_home))
    if raw_config is not None:
        config_text = config_path.read_text(encoding="utf-8")
        results.append(local_only_hosts_result(config_text))
        results.append(secret_like_config_result(config_text))
        results.append(placeholder_targets_result(raw_config))
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


def forbidden_artifacts_result(runtime_home: Path) -> CheckResult:
    matches: list[str] = []
    for pattern in FORBIDDEN_ARTIFACT_PATTERNS:
        matches.extend(
            relative_detail(path, runtime_home)
            for path in runtime_home.glob(pattern)
            if path.is_file()
        )
    matches = sorted(set(matches))
    return CheckResult(
        "forbidden_runtime_artifacts",
        not matches,
        "none" if not matches else ",".join(matches[:20]),
    )


def local_only_hosts_result(config_text: str) -> CheckResult:
    matches = sorted(
        {
            match.group(0)
            for pattern in LOCAL_ONLY_PATTERNS
            for match in pattern.finditer(config_text)
        }
    )
    return CheckResult(
        "local_only_hosts",
        not matches,
        "none" if not matches else ",".join(matches),
    )


def secret_like_config_result(config_text: str) -> CheckResult:
    names = []
    for line_no, line in enumerate(config_text.splitlines(), start=1):
        if any(pattern.search(line) for pattern in SECRET_LIKE_PATTERNS):
            names.append(f"config/routes.yaml:{line_no}")
    return CheckResult(
        "secret_like_config_values",
        not names,
        "none" if not names else ",".join(names[:20]),
    )


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


def relative_detail(path: Path, runtime_home: Path) -> str:
    try:
        return path.relative_to(runtime_home).as_posix()
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
