from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from router.config import load_settings
from router.config import resolve_route_bank_path


def verify_route_contract(routes_path: Path, cases_path: Path) -> list[str]:
    errors: list[str] = []

    raw = yaml.safe_load(routes_path.read_text(encoding="utf-8")) or {}
    routes = raw.get("routes", {}) or {}
    route_ids = set(routes)

    entry_model = raw.get("entry_model", raw.get("route_model", "semantic-router"))
    if entry_model in route_ids:
        errors.append(
            f"entry model '{entry_model}' must not also be a route_id in routes"
        )

    fallback_route_id = raw.get("fallback_route_id", raw.get("default_route", "fast"))
    if fallback_route_id not in route_ids:
        errors.append(
            f"fallback_route_id '{fallback_route_id}' must be present in routes"
        )

    for hard_rule in raw.get("hard_rules", []) or []:
        route_id = hard_rule.get("route_id")
        if route_id not in route_ids:
            errors.append(f"hard_rules route_id '{route_id}' must be present in routes")

    errors.extend(verify_route_bank_contract(raw, routes_path.parent, route_ids))

    try:
        settings = load_settings(routes_path)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"failed to load route settings: {exc}")
        return errors

    for route_id, spec in settings.routes.items():
        if not spec.target_model:
            errors.append(f"route '{route_id}' has no resolved target_model")
        if spec.target_model == settings.route_model:
            errors.append(
                f"route '{route_id}' target_model must not equal entry model '{settings.route_model}'"
            )

    cases_raw = yaml.safe_load(cases_path.read_text(encoding="utf-8")) or {}
    cases = cases_raw.get("cases", []) or []
    target_models = {spec.target_model for spec in settings.routes.values() if spec.target_model}
    for idx, case in enumerate(cases, start=1):
        expect = case.get("expect")
        if expect in target_models and expect not in route_ids:
            errors.append(
                f"eval case #{idx} expect '{expect}' looks like a target_model; use route_id instead"
            )
        elif expect not in route_ids:
            errors.append(
                f"eval case #{idx} expect '{expect}' is not a configured route_id"
            )

    return errors


def verify_route_bank_contract(
    raw: dict,
    base_dir: Path,
    route_ids: set[str],
) -> list[str]:
    route_bank_path = raw.get("route_bank_path")
    if not route_bank_path:
        return []

    bank_path = resolve_route_bank_path(route_bank_path, base_dir)
    if not bank_path.exists():
        return []

    bank_raw = yaml.safe_load(bank_path.read_text(encoding="utf-8")) or {}
    bank_routes = bank_raw.get("routes", {}) or {}
    bank_route_ids = set(bank_routes)
    unknown_bank_routes = sorted(bank_route_ids - route_ids)
    matched_bank_routes = sorted(bank_route_ids & route_ids)
    errors: list[str] = []

    if bank_route_ids and not matched_bank_routes:
        errors.append(
            f"route_bank_path '{route_bank_path}' has no route_id keys matching routes"
        )
    for route_id in unknown_bank_routes:
        errors.append(
            f"route_bank_path '{route_bank_path}' contains unknown route_id '{route_id}'"
        )
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify route_id/target_model contract consistency")
    parser.add_argument("--routes", default="config/routes.yaml")
    parser.add_argument("--cases", default="config/eval_cases.yaml")
    args = parser.parse_args()

    errors = verify_route_contract(Path(args.routes), Path(args.cases))
    if errors:
        print("Route contract verification failed:")
        for error in errors:
            print(f" - {error}")
        raise SystemExit(1)

    print("Route contract verification passed.")


if __name__ == "__main__":
    main()
