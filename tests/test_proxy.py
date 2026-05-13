from __future__ import annotations

from router.proxy import LiteLLMProxy, forwardable_headers, response_headers


def test_forwardable_headers_drop_inbound_authorization_by_default():
    headers = forwardable_headers(
        {
            "authorization": "Bearer inbound-client-key",
            "content-type": "application/json",
            "x-request-id": "req-1",
        }
    )

    assert headers == {
        "content-type": "application/json",
        "x-request-id": "req-1",
    }


def test_forwardable_headers_use_explicit_upstream_api_key():
    headers = forwardable_headers(
        {
            "authorization": "Bearer inbound-client-key",
            "content-type": "application/json",
        },
        upstream_api_key="sk-upstream",
    )

    assert headers["authorization"] == "Bearer sk-upstream"
    assert "inbound-client-key" not in str(headers)


def test_litellm_proxy_accepts_explicit_upstream_api_key():
    proxy = LiteLLMProxy("http://litellm:4000", api_key="sk-upstream")

    assert proxy.api_key == "sk-upstream"


def test_response_headers_drop_protocol_generated_server_and_date_headers():
    headers = response_headers(
        {
            "content-type": "application/json",
            "server": "upstream-server",
            "date": "Sun, 03 May 2026 10:00:00 GMT",
            "x-upstream": "kept",
        }
    )

    assert headers == {
        "content-type": "application/json",
        "x-upstream": "kept",
    }
