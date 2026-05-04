from __future__ import annotations

import argparse
import os
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


def require_header(
    *,
    name: str,
    headers: dict[str, str],
    key: str,
    expected: str,
) -> CheckResult:
    value = headers.get(key)
    if value is None:
        return CheckResult(name, False, f"missing header {key}")
    if value != expected:
        return CheckResult(name, False, f"{key}={value}, expected {expected}")
    return CheckResult(name, True, f"{key}={value}")


def require_json_field(
    *,
    name: str,
    payload: dict,
    key: str,
    expected: str,
) -> CheckResult:
    value = payload.get(key)
    if value != expected:
        return CheckResult(name, False, f"{key}={value}, expected {expected}")
    return CheckResult(name, True, f"{key}={value}")


def summarize_results(results: list[CheckResult]) -> None:
    for result in results:
        status = "PASS" if result.ok else "FAIL"
        print(f"{status}\t{result.name}\t{result.detail}")
    if not all(result.ok for result in results):
        raise SystemExit(1)


def chat_payload(stream: bool) -> dict:
    return {
        "model": "semantic-router",
        "stream": stream,
        "messages": [
            {
                "role": "user",
                "content": "这个线上 bug 为什么偶发？只回答 OK",
            }
        ],
        "max_tokens": 8,
    }


def run_preflight(router_base_url: str, api_key: str, timeout: float) -> list[CheckResult]:
    base_url = router_base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {api_key}"}
    results: list[CheckResult] = []

    with httpx.Client(timeout=timeout) as client:
        health = client.get(f"{base_url}/health")
        results.append(
            CheckResult("health_status", health.status_code == 200, f"status={health.status_code}")
        )
        if health.status_code == 200:
            results.append(
                require_json_field(
                    name="health_payload",
                    payload=health.json(),
                    key="status",
                    expected="ok",
                )
            )

        ready = client.get(f"{base_url}/ready")
        results.append(
            CheckResult("ready_status", ready.status_code == 200, f"status={ready.status_code}")
        )
        if ready.status_code == 200:
            ready_payload = ready.json()
            ready_value = ready_payload.get("ready")
            results.append(
                CheckResult(
                    "ready_payload",
                    ready_value is True,
                    f"ready={ready_value}",
                )
            )

        nonstream = client.post(
            f"{base_url}/v1/chat/completions",
            headers=headers,
            json=chat_payload(stream=False),
        )
        results.append(
            CheckResult(
                "nonstream_status",
                nonstream.status_code == 200,
                f"status={nonstream.status_code}",
            )
        )
        results.append(
            require_header(
                name="nonstream_route",
                headers={key.lower(): value for key, value in nonstream.headers.items()},
                key="x-router-target-model",
                expected="pro-router",
            )
        )

        with client.stream(
            "POST",
            f"{base_url}/v1/chat/completions",
            headers=headers,
            json=chat_payload(stream=True),
        ) as stream_response:
            body_head = next(stream_response.iter_bytes(), b"")
            results.append(
                CheckResult(
                    "stream_status",
                    stream_response.status_code == 200,
                    f"status={stream_response.status_code}",
                )
            )
            results.append(
                require_header(
                    name="stream_route",
                    headers={key.lower(): value for key, value in stream_response.headers.items()},
                    key="x-router-target-model",
                    expected="pro-router",
                )
            )
            results.append(
                CheckResult(
                    "stream_body",
                    body_head.startswith(b"data:"),
                    f"starts_with_data={body_head.startswith(b'data:')}",
                )
            )

    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--router-base-url",
        default=os.getenv("ROUTER_BASE_URL", "http://127.0.0.1:4001"),
    )
    parser.add_argument("--api-key", default=os.getenv("LITELLM_MASTER_KEY"))
    parser.add_argument("--timeout", type=float, default=45.0)
    args = parser.parse_args()

    if not args.api_key:
        raise SystemExit("LITELLM_MASTER_KEY or --api-key is required")
    summarize_results(run_preflight(args.router_base_url, args.api_key, args.timeout))


if __name__ == "__main__":
    main()
