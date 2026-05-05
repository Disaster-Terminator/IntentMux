from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    from router.config import load_settings
    from scripts.check_route_error_budget import BudgetConfig, check_budget, format_budget_result
    from scripts.router_log_summary import (
        ParseDiagnostics,
        format_summary,
        parse_route_records,
        summarize_records,
    )
except ModuleNotFoundError:
    from router.config import load_settings
    from check_route_error_budget import BudgetConfig, check_budget, format_budget_result
    from router_log_summary import (
        ParseDiagnostics,
        format_summary,
        parse_route_records,
        summarize_records,
    )


def render_config_section(routes_path: str) -> str:
    settings = load_settings(routes_path)
    route_targets = {
        route_id: route_spec.target_model or route_id
        for route_id, route_spec in sorted(settings.routes.items())
    }
    hard_route_ids = sorted({rule.route_id for rule in settings.hard_rules})

    lines = [
        "[router_config]",
        f"entry_model: {settings.entry_model}",
        f"fallback_route_id: {settings.fallback_route_id}",
        "route_targets:",
    ]
    lines.extend([f"  {route_id}: {target}" for route_id, target in route_targets.items()])
    lines.append(
        "hard_rule_route_ids: "
        + (", ".join(hard_route_ids) if hard_route_ids else "none")
    )
    return "\n".join(lines)


def render_logs_sections(logs_path: str) -> str:
    diagnostics = ParseDiagnostics()
    records = list(parse_route_records(Path(logs_path).read_text(encoding="utf-8").splitlines(), diagnostics=diagnostics))
    route_summary = summarize_records(records, parse_diagnostics=diagnostics)
    budget_result = check_budget(
        records,
        BudgetConfig(
            min_total=0,
            max_error_rate=1.0,
            max_target_error_rate=1.0,
            max_route_error_rate=1.0,
        ),
        parse_diagnostics=diagnostics,
    )
    return "\n".join(
        [
            "[route_summary]",
            format_summary(route_summary),
            "[route_error_budget]",
            format_budget_result(budget_result),
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print a prompt-safe router diagnostics summary from config and logs."
    )
    parser.add_argument("--routes", required=True, help="Path to config/routes.yaml")
    parser.add_argument("--logs", help="Optional path to structured router log file")
    args = parser.parse_args(argv)

    sections = [render_config_section(args.routes)]
    if args.logs:
        sections.append(render_logs_sections(args.logs))

    sys.stdout.write("\n\n".join(sections) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
