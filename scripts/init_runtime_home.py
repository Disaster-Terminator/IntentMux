#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATE = REPO_ROOT / "examples" / "intentmux-home"
DEFAULT_RUNTIME_HOME = REPO_ROOT / ".intentmux-home"


def copy_template(template: Path, runtime_home: Path) -> list[Path]:
    created: list[Path] = []
    for source in sorted(template.rglob("*")):
        relative = source.relative_to(template)
        target = runtime_home / relative
        if source.is_dir():
            if not target.exists():
                target.mkdir(parents=True)
                created.append(target)
            continue
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        created.append(target)
    return created


def ensure_runtime_dirs(runtime_home: Path) -> list[Path]:
    created: list[Path] = []
    for relative in (
        "logs/routes",
        "logs/prompts",
        "logs/health",
        "logs/quality",
        "reviews",
        "cache",
    ):
        path = runtime_home / relative
        if not path.exists():
            path.mkdir(parents=True)
            created.append(path)
    return created


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Initialize the ignored local IntentMux runtime home."
    )
    parser.add_argument(
        "--runtime-home",
        type=Path,
        default=DEFAULT_RUNTIME_HOME,
        help="Runtime home to initialize. Defaults to repository .intentmux-home.",
    )
    parser.add_argument(
        "--template",
        type=Path,
        default=DEFAULT_TEMPLATE,
        help="Template directory to copy. Defaults to examples/intentmux-home.",
    )
    args = parser.parse_args(argv)

    template = args.template.expanduser()
    runtime_home = args.runtime_home.expanduser()
    if not template.is_dir():
        raise SystemExit(f"template directory not found: {template}")

    runtime_home.mkdir(parents=True, exist_ok=True)
    copied = copy_template(template, runtime_home)
    created_dirs = ensure_runtime_dirs(runtime_home)

    print(f"runtime_home={runtime_home}")
    print(f"template={template}")
    print(f"copied={len(copied)}")
    print(f"created_dirs={len(created_dirs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
