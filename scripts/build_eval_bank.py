from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml


def build_eval_bank(
    manual_cases: list[dict[str, str]],
    route_bank: dict[str, Any],
    per_route_limit: int,
) -> dict[str, list[dict[str, str]]]:
    cases: list[dict[str, str]] = []
    seen: set[str] = set()

    for case in manual_cases:
        text = case["text"]
        if text in seen:
            continue
        cases.append(
            {
                "text": text,
                "expect": case["expect"],
                "source": case.get("source", "manual"),
            }
        )
        seen.add(text)

    for route, payload in route_bank.get("routes", {}).items():
        added_for_route = 0
        for item in payload.get("utterances", []):
            text = item["text"] if isinstance(item, dict) else str(item)
            if text in seen:
                continue
            source = item.get("source", "route_bank") if isinstance(item, dict) else "route_bank"
            cases.append({"text": text, "expect": route, "source": source})
            seen.add(text)
            added_for_route += 1
            if added_for_route >= per_route_limit:
                break

    return {"cases": cases}


def load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_manual_cases(paths: list[Path]) -> list[dict[str, str]]:
    cases: list[dict[str, str]] = []
    for path in paths:
        payload = load_yaml(path)
        cases.extend(payload["cases"])
    return cases


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manual-cases",
        action="append",
        default=["config/eval_cases.yaml"],
        help="YAML case file. Repeat to include redacted production review cases.",
    )
    parser.add_argument("--route-bank", default="data/semantic_sets/route_bank.yaml")
    parser.add_argument("--output", default="data/semantic_sets/eval_bank.yaml")
    parser.add_argument("--per-route-limit", type=int, default=80)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    manual_cases = load_manual_cases([repo_root / path for path in args.manual_cases])
    route_bank = load_yaml(repo_root / args.route_bank)
    eval_bank = build_eval_bank(
        manual_cases=manual_cases,
        route_bank=route_bank,
        per_route_limit=args.per_route_limit,
    )

    output = repo_root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        yaml.safe_dump(eval_bank, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print(f"wrote {output} with {len(eval_bank['cases'])} cases")


if __name__ == "__main__":
    main()
