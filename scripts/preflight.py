from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass

import httpx


STREAM_PREFLIGHT_MAX_CHUNKS = 32
STREAM_PREFLIGHT_MAX_BYTES = 65536


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


def require_header_present(
    *,
    name: str,
    headers: dict[str, str],
    key: str,
) -> CheckResult:
    value = headers.get(key)
    if value is None:
        return CheckResult(name, False, f"missing header {key}")
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


def ready_payload_result(payload: dict) -> CheckResult:
    ready_value = payload.get("ready")
    degraded_components = []
    components = payload.get("components")
    if isinstance(components, dict):
        for name, status in sorted(components.items()):
            if not isinstance(status, dict) or status.get("ok") is not False:
                continue
            detail = status.get("detail") or "degraded"
            degraded_components.append(f"{name}:{detail}")

    detail = f"ready={ready_value}"
    if degraded_components:
        detail += f" degraded={','.join(degraded_components)}"
    return CheckResult("ready_payload", ready_value is True, detail)


def target_model_check(
    *,
    name: str,
    headers: dict[str, str],
    expected_target_model: str | None,
) -> CheckResult:
    if expected_target_model:
        return require_header(
            name=name,
            headers=headers,
            key="x-router-target-model",
            expected=expected_target_model,
        )
    return require_header_present(
        name=name,
        headers=headers,
        key="x-router-target-model",
    )


def validate_nonstream_chat_response(
    response: httpx.Response,
    *,
    expected_target_model: str | None = None,
) -> list[CheckResult]:
    return [
        CheckResult(
            "nonstream_status",
            response.status_code == 200,
            f"status={response.status_code}",
        ),
        target_model_check(
            name="nonstream_route",
            headers={key.lower(): value for key, value in response.headers.items()},
            expected_target_model=expected_target_model,
        ),
    ]


def validate_streaming_sse_response(
    response: httpx.Response,
    body_head: bytes,
    *,
    expected_target_model: str | None = None,
) -> list[CheckResult]:
    starts_with_data = body_head.startswith(b"data:")
    has_done = b"data: [DONE]" in body_head
    return [
        CheckResult(
            "stream_status",
            response.status_code == 200,
            f"status={response.status_code}",
        ),
        target_model_check(
            name="stream_route",
            headers={key.lower(): value for key, value in response.headers.items()},
            expected_target_model=expected_target_model,
        ),
        CheckResult(
            "stream_body",
            starts_with_data,
            f"starts_with_data={starts_with_data}",
        ),
        CheckResult(
            "stream_complete",
            has_done,
            f"has_done={has_done}",
        ),
    ]


def read_bounded_stream_body_head(
    response: httpx.Response,
    *,
    max_chunks: int = STREAM_PREFLIGHT_MAX_CHUNKS,
    max_bytes: int = STREAM_PREFLIGHT_MAX_BYTES,
) -> bytes:
    chunks: list[bytes] = []
    total = 0
    for index, chunk in enumerate(response.iter_bytes(), start=1):
        if not chunk:
            continue
        remaining = max_bytes - total
        if remaining <= 0:
            break
        chunks.append(chunk[:remaining])
        total += min(len(chunk), remaining)
        body = b"".join(chunks)
        if b"data: [DONE]" in body or index >= max_chunks or total >= max_bytes:
            return body
    return b"".join(chunks)


def check_readiness(
    client: httpx.Client,
    base_url: str,
    *,
    headers: dict[str, str],
    attempts: int,
    interval: float,
) -> list[CheckResult]:
    attempts = max(1, attempts)
    last_results: list[CheckResult] = []
    for attempt in range(attempts):
        ready = client.get(f"{base_url}/ready", headers=headers)
        last_results = [
            CheckResult(
                "ready_status",
                ready.status_code == 200,
                f"status={ready.status_code}",
            )
        ]
        try:
            last_results.append(ready_payload_result(ready.json()))
        except Exception as exc:
            last_results.append(
                CheckResult(
                    "ready_payload",
                    False,
                    f"invalid_json={type(exc).__name__}",
                )
            )
        if all(result.ok for result in last_results):
            return last_results
        if attempt < attempts - 1 and interval > 0:
            time.sleep(interval)
    return last_results


def require_unauthenticated_rejected(
    *,
    name: str,
    response: httpx.Response,
) -> CheckResult:
    ok = response.status_code in {401, 403}
    return CheckResult(name, ok, f"status={response.status_code}")


def check_unauthenticated_rejections(
    client: httpx.Client,
    base_url: str,
    *,
    model: str,
) -> list[CheckResult]:
    ready = client.get(f"{base_url}/ready", headers={})
    models = client.get(f"{base_url}/v1/models", headers={})
    chat = client.post(
        f"{base_url}/v1/chat/completions",
        headers={},
        json=chat_payload(stream=False, model=model),
    )
    return [
        require_unauthenticated_rejected(name="unauth_ready", response=ready),
        require_unauthenticated_rejected(name="unauth_models", response=models),
        require_unauthenticated_rejected(name="unauth_chat", response=chat),
    ]


def summarize_results(results: list[CheckResult]) -> None:
    for result in results:
        status = "PASS" if result.ok else "FAIL"
        print(f"{status}\t{result.name}\t{result.detail}")
    if not all(result.ok for result in results):
        raise SystemExit(1)


def chat_payload(stream: bool, *, model: str = "auto") -> dict:
    return {
        "model": model,
        "stream": stream,
        "messages": [
            {
                "role": "user",
                "content": "这个线上 bug 为什么偶发？只回答 OK",
            }
        ],
        "max_tokens": 8,
    }


def run_preflight(
    router_base_url: str,
    intentmux_api_key: str | None,
    timeout: float,
    ready_attempts: int = 3,
    ready_interval: float = 1.0,
    expected_target_model: str | None = None,
    model: str = "auto",
    require_unauth_rejected: bool = False,
) -> list[CheckResult]:
    base_url = router_base_url.rstrip("/")
    headers = (
        {"Authorization": f"Bearer {intentmux_api_key}"}
        if intentmux_api_key
        else {}
    )
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
        if require_unauth_rejected:
            results.extend(
                check_unauthenticated_rejections(client, base_url, model=model)
            )

        results.extend(
            check_readiness(
                client,
                base_url,
                headers=headers,
                attempts=ready_attempts,
                interval=ready_interval,
            )
        )

        nonstream = client.post(
            f"{base_url}/v1/chat/completions",
            headers=headers,
            json=chat_payload(stream=False, model=model),
        )
        results.extend(
            validate_nonstream_chat_response(
                nonstream,
                expected_target_model=expected_target_model,
            )
        )

        with client.stream(
            "POST",
            f"{base_url}/v1/chat/completions",
            headers=headers,
            json=chat_payload(stream=True, model=model),
        ) as stream_response:
            body_head = read_bounded_stream_body_head(stream_response)
            results.extend(
                validate_streaming_sse_response(
                    stream_response,
                    body_head,
                    expected_target_model=expected_target_model,
                )
            )

    return results


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--router-base-url",
        default=os.getenv("ROUTER_BASE_URL", "http://127.0.0.1:4001"),
    )
    parser.add_argument(
        "--intentmux-api-key",
        default=os.getenv("ROUTER_INBOUND_API_KEY"),
        help="Optional IntentMux inbound API key for direct sidecar preflight.",
    )
    parser.add_argument(
        "--api-key",
        dest="legacy_api_key",
        help=(
            "Deprecated alias for --intentmux-api-key. "
            "This is not the upstream LiteLLM key."
        ),
    )
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument(
        "--expected-target-model",
        default=os.getenv("INTENTMUX_PREFLIGHT_EXPECTED_TARGET_MODEL"),
        help=(
            "Optional deployment-specific target model assertion. "
            "If omitted, preflight only requires the route header to be present."
        ),
    )
    parser.add_argument(
        "--model",
        default=os.getenv("INTENTMUX_PREFLIGHT_MODEL", "auto"),
        help="Model name used by chat probes. Default: auto.",
    )
    parser.add_argument("--ready-attempts", type=int, default=3)
    parser.add_argument("--ready-interval", type=float, default=1.0)
    parser.add_argument(
        "--require-unauth-rejected",
        action="store_true",
        help="Require unauthenticated /ready, /v1/models, and chat probes to be rejected.",
    )
    args = parser.parse_args(argv)
    intentmux_api_key = args.intentmux_api_key or args.legacy_api_key
    if args.legacy_api_key and not args.intentmux_api_key:
        print(
            "warning: --api-key is deprecated for preflight; use --intentmux-api-key",
            file=sys.stderr,
        )

    summarize_results(
        run_preflight(
            args.router_base_url,
            intentmux_api_key,
            args.timeout,
            ready_attempts=args.ready_attempts,
            ready_interval=args.ready_interval,
            expected_target_model=args.expected_target_model,
            model=args.model,
            require_unauth_rejected=args.require_unauth_rejected,
        )
    )


if __name__ == "__main__":
    main()
