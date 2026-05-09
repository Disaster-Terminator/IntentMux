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


def test_verify_route_contract_rejects_route_bank_target_model_keys(tmp_path: Path):
    bank_dir = tmp_path / "semantic_sets"
    bank_dir.mkdir()
    (bank_dir / "route_bank.yaml").write_text(
        """
version: 1
routes:
  cheap-router:
    utterances:
      - text: hello
  pro-router:
    utterances:
      - text: debug
""",
        encoding="utf-8",
    )
    routes_path = write_routes(
        tmp_path,
        """
route_model: semantic-router
fallback_route_id: fast
route_bank_path: semantic_sets/route_bank.yaml
routes:
  fast:
    target_model: cheap-router
    description: low risk
    utterances: [hello]
  strong:
    target_model: pro-router
    description: high risk
    utterances: [debug]
""",
    )
    cases_path = write_cases(
        tmp_path,
        """
cases:
  - text: hello
    expect: fast
""",
    )

    errors = verify_route_contract(routes_path, cases_path)

    assert any("has no route_id keys matching routes" in error for error in errors)
    assert any("unknown route_id 'cheap-router'" in error for error in errors)
    assert any("unknown route_id 'pro-router'" in error for error in errors)


def test_verify_route_contract_allows_route_bank_route_id_keys(tmp_path: Path):
    bank_dir = tmp_path / "semantic_sets"
    bank_dir.mkdir()
    (bank_dir / "route_bank.yaml").write_text(
        """
version: 1
routes:
  fast:
    utterances:
      - text: hello
  strong:
    utterances:
      - text: debug
""",
        encoding="utf-8",
    )
    routes_path = write_routes(
        tmp_path,
        """
route_model: semantic-router
fallback_route_id: fast
route_bank_path: semantic_sets/route_bank.yaml
routes:
  fast:
    target_model: cheap-router
    description: low risk
    utterances: [hello]
  strong:
    target_model: pro-router
    description: high risk
    utterances: [debug]
""",
    )
    cases_path = write_cases(
        tmp_path,
        """
cases:
  - text: hello
    expect: fast
""",
    )

    assert verify_route_contract(routes_path, cases_path) == []
