from __future__ import annotations

import pytest

from scripts.eval_routes import EvalCase, validate_case_routes


def test_validate_case_routes_accepts_known_route_ids():
    validate_case_routes([EvalCase(text="x", expect="fast")], {"fast", "strong"})


def test_validate_case_routes_rejects_target_model_like_expect():
    with pytest.raises(ValueError, match="not in routes config"):
        validate_case_routes([EvalCase(text="x", expect="pro-router")], {"fast", "strong"})
