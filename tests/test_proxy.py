from __future__ import annotations

from router.proxy import response_headers


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
