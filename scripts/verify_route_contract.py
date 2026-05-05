from __future__ import annotations

import argparse
from pathlib import Path

import yaml


def _resolved_target_model(route_id: str, route_spec: dict) -> str:
    target_model = route_spec.get("target_model")
    if target_model is None:
        return route_id
    return str(target_model)


def verify_route_contract(routes_path: Path, eval_cases_path: Path | None = None) -> list[str]:
    raw = yaml.safe_load(routes_path.read_text(encoding="utf-8")) or {}
    routes = raw.get("routes") or {}
    route_ids = set(routes)
    route_model = raw.get("route_model") or raw.get("entry_model") or "semantic-router"

    errors: list[str] = []

    if route_model in route_ids:
        errors.append(f"route_model/entry_model '{route_model}' must not be a route_id")

    fallback_route_id = raw.get("fallback_route_id") or raw.get("default_route")
    if fallback_route_id not in route_ids:
        errors.append(
            f"fallback_route_id/default_route '{fallback_route_id}' must exist in routes"
        )

    hard_rules = raw.get("hard_rules") or []
    for index, hard_rule in enumerate(hard_rules, start=1):
        hard_rule_route_id = hard_rule.get("route_id")
        if hard_rule_route_id not in route_ids:
            errors.append(
                f"hard_rules[{index}] route_id '{hard_rule_route_id}' must exist in routes"
            )

    target_models = set()
    for route_id, route_spec in routes.items():
        resolved_target_model = _resolved_target_model(route_id, route_spec)
        if not resolved_target_model:
            errors.append(f"routes.{route_id} must resolve a non-empty target_model")
            continue
        if resolved_target_model == route_model:
            errors.append(
                f"routes.{route_id} resolved target_model '{resolved_target_model}' must not equal entry model"
            )
        target_models.add(resolved_target_model)

    if eval_cases_path is not None:
        eval_cases_raw = yaml.safe_load(eval_cases_path.read_text(encoding="utf-8")) or {}
        for index, case in enumerate(eval_cases_raw.get("cases") or [], start=1):
            expect = case.get("expect")
            if expect in target_models and expect not in route_ids:
                errors.append(
                    f"eval case {index} expect '{expect}' matches a target_model; use route_id instead"
                )
            elif expect not in route_ids:
                errors.append(f"eval case {index} expect '{expect}' must be a configured route_id")

    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--routes", default="config/routes.yaml")
    parser.add_argument("--eval-cases", default="config/eval_cases.yaml")
    args = parser.parse_args()

    errors = verify_route_contract(Path(args.routes), Path(args.eval_cases))
    if errors:
        print("Route contract verification failed:")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)

    print(
        "Route contract verification passed "
        f"for {args.routes} and {args.eval_cases}."
    )


if __name__ == "__main__":
    main()
