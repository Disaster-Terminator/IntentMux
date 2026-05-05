from __future__ import annotations

from pathlib import Path

from scripts.verify_route_contract import verify_route_contract


def write_routes(path: Path, body: str) -> Path:
    routes_path = path / "routes.yaml"
    routes_path.write_text(body, encoding="utf-8")
    return routes_path


def write_cases(path: Path, body: str) -> Path:
    cases_path = path / "eval_cases.yaml"
    cases_path.write_text(body, encoding="utf-8")
    return cases_path


def test_verify_route_contract_passes_for_valid_contract(tmp_path: Path):
    routes_path = write_routes(
        tmp_path,
        """
route_model: semantic-router
fallback_route_id: fast
routes:
  fast:
    target_model: cheap-router
    description: low risk
    utterances: [hello]
  strong:
    target_model: pro-router
    description: high risk
    utterances: [debug]
hard_rules:
  - route_id: strong
    keywords: [PR]
""",
    )
    cases_path = write_cases(
        tmp_path,
        """
cases:
  - text: say hi
    expect: fast
  - text: debug this
    expect: strong
""",
    )

    assert verify_route_contract(routes_path, cases_path) == []


def test_verify_route_contract_reports_target_model_and_missing_references(tmp_path: Path):
    routes_path = write_routes(
        tmp_path,
        """
route_model: semantic-router
fallback_route_id: missing
routes:
  semantic-router:
    target_model: cheap-router
    description: bad recursion
    utterances: [hello]
  strong:
    target_model: semantic-router
    description: bad target model
    utterances: [debug]
hard_rules:
  - route_id: experimental
    keywords: [probe]
""",
    )
    cases_path = write_cases(
        tmp_path,
        """
cases:
  - text: hello
    expect: cheap-router
""",
    )

    errors = verify_route_contract(routes_path, cases_path)

    assert any("entry model 'semantic-router'" in error for error in errors)
    assert any("fallback_route_id 'missing'" in error for error in errors)
    assert any("hard_rules route_id 'experimental'" in error for error in errors)
    assert any("failed to load route settings" in error for error in errors)


def test_verify_route_contract_rejects_eval_expect_target_model(tmp_path: Path):
    routes_path = write_routes(
        tmp_path,
        """
route_model: semantic-router
fallback_route_id: fast
routes:
  fast:
    target_model: cheap-router
    description: low risk
    utterances: [hello]
""",
    )
    cases_path = write_cases(
        tmp_path,
        """
cases:
  - text: hello
    expect: cheap-router
""",
    )

    errors = verify_route_contract(routes_path, cases_path)

    assert any("looks like a target_model" in error for error in errors)
