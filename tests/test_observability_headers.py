from __future__ import annotations

from router.observability import route_headers


def test_route_headers_include_optional_route_and_policy_ids_with_encoding():
    headers = route_headers(
        target_model="pro router",
        reason="hard_rule:线上",
        request_id="req 1",
        route_id="deep 路线",
        policy_id="hard rule",
    )

    assert headers == {
        "x-router-request-id": "req%201",
        "x-router-target-model": "pro%20router",
        "x-router-reason": "hard_rule:%E7%BA%BF%E4%B8%8A",
        "x-router-route-id": "deep%20%E8%B7%AF%E7%BA%BF",
        "x-router-policy-id": "hard%20rule",
    }


def test_route_headers_omit_route_and_policy_when_absent():
    headers = route_headers(
        target_model="deepseek-v4-pro",
        reason="passthrough",
        request_id="req-2",
        route_id=None,
        policy_id=None,
    )

    assert "x-router-route-id" not in headers
    assert "x-router-policy-id" not in headers
