from __future__ import annotations

from pathlib import Path

from scripts.verify_route_contract import verify_route_contract


def test_verify_route_contract_passes_for_valid_config(tmp_path: Path):
    routes_path = tmp_path / "routes.yaml"
    eval_cases_path = tmp_path / "eval_cases.yaml"

    routes_path.write_text(
        """
entry_model: semantic-router
fallback_route_id: fast
routes:
  fast:
    target_model: cheap-router
    description: low risk
    utterances: [hi]
  strong:
    target_model: pro-router
    description: high risk
    utterances: [debug]
hard_rules:
  - route_id: strong
    keywords: [PR]
""",
        encoding="utf-8",
    )
    eval_cases_path.write_text(
        """
cases:
  - text: hello
    expect: fast
  - text: review this patch
    expect: strong
""",
        encoding="utf-8",
    )

    assert verify_route_contract(routes_path, eval_cases_path) == []


def test_verify_route_contract_reports_drift_and_missing_references(tmp_path: Path):
    routes_path = tmp_path / "routes.yaml"
    eval_cases_path = tmp_path / "eval_cases.yaml"

    routes_path.write_text(
        """
route_model: semantic-router
fallback_route_id: missing
routes:
  semantic-router:
    target_model: semantic-router
    description: loop
    utterances: [loop]
  fast:
    target_model: cheap-router
    description: low risk
    utterances: [hi]
hard_rules:
  - route_id: strong
    keywords: [PR]
""",
        encoding="utf-8",
    )
    eval_cases_path.write_text(
        """
cases:
  - text: hello
    expect: cheap-router
  - text: unknown
    expect: ghost
""",
        encoding="utf-8",
    )

    errors = verify_route_contract(routes_path, eval_cases_path)

    assert any("must not be a route_id" in error for error in errors)
    assert any("must exist in routes" in error for error in errors)
    assert any("matches a target_model" in error for error in errors)
    assert any("must be a configured route_id" in error for error in errors)
