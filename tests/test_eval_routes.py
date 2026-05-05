from __future__ import annotations

import pytest

from scripts.eval_routes import EvalCase, validate_case_route_ids


def test_validate_case_route_ids_accepts_known_route_id():
    validate_case_route_ids([EvalCase(text="hi", expect="fast")], {"fast", "strong"})


def test_validate_case_route_ids_rejects_target_model_name():
    with pytest.raises(ValueError, match="pro-router"):
        validate_case_route_ids([EvalCase(text="hi", expect="pro-router")], {"fast", "strong"})
