from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
import subprocess
import time
import uuid
from collections.abc import Callable
from collections.abc import Sequence
from typing import Any

import httpx


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class Probe:
    name: str
    prompt: str
    expected_route: str
    expected_target_model: str
    stream: bool = False


DEFAULT_PROBES = [
    Probe(
        name="deep_nonstream",
        prompt="这个线上 bug 为什么偶发？只回答 OK",
        expected_route="deep",
        expected_target_model="your-deep-model",
    ),
    Probe(
        name="deep_stream",
        prompt="这个线上 bug 为什么偶发？只回答 OK",
        expected_route="deep",
        expected_target_model="your-deep-model",
        stream=True,
    ),
    Probe(
        name="lite_nonstream",
        prompt="帮我把这段话润色一下，只回答 OK",
        expected_route="lite",
        expected_target_model="your-lite-model",
    ),
]


def parse_route_logs(raw_logs: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in raw_logs.splitlines():
        line = route_log_line_from_transport(line)
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            record = parse_route_log_fragment(line)
            if record is None:
                continue
        if "Log" in record and isinstance(record["Log"], str):
            nested = parse_route_log_fragment(record["Log"])
            if nested is None:
                continue
            record = nested
        if record.get("event") in {"route_complete", "route_error"}:
            records.append(record)
    return records


def route_log_line_from_transport(line: str) -> str:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return line
    if isinstance(payload, dict) and isinstance(payload.get("Log"), str):
        return payload["Log"]
    return line


def parse_route_log_fragment(line: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        return payload
    candidate_indexes = [
        index
        for index in (line.find('"duration_ms"'), line.find('"event"'))
        if index >= 0
    ]
    if not candidate_indexes:
        return None
    fragment = "{" + line[min(candidate_indexes) :]
    try:
        payload = json.loads(fragment)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict):
        return payload
    return None


def find_route_log(
    route_logs: list[dict[str, Any]], *, request_id: str, stream: bool
) -> dict[str, Any] | None:
    for record in reversed(route_logs):
        if record.get("request_id") == request_id and record.get("stream") is stream:
            return record
    return None


def find_matching_route_log(
    route_logs: list[dict[str, Any]],
    *,
    probe: Probe,
    used_indexes: set[int],
) -> tuple[int, dict[str, Any]] | None:
    for index in range(len(route_logs) - 1, -1, -1):
        if index in used_indexes:
            continue
        record = route_logs[index]
        if (
            record.get("event") == "route_complete"
            and record.get("source_model") == "intentmux"
            and record.get("route_id") == probe.expected_route
            and record.get("target_model") == probe.expected_target_model
            and record.get("stream") is probe.stream
            and record.get("upstream_status") == 200
        ):
            return index, record
    return None


def resolve_probe_expectations(
    probes: Sequence[Probe],
    *,
    router_base_url: str,
    intentmux_api_key: str | None,
    timeout: float,
) -> list[Probe]:
    resolved: list[Probe] = []
    headers = {"Content-Type": "application/json"}
    if intentmux_api_key:
        headers["Authorization"] = f"Bearer {intentmux_api_key}"
    base_url = router_base_url.rstrip("/")
    with httpx.Client(timeout=timeout) as client:
        for probe in probes:
            response = client.post(
                f"{base_url}/v1/intentmux/decision",
                json={
                    "model": "intentmux",
                    "messages": [{"role": "user", "content": probe.prompt}],
                },
                headers=headers,
            )
            if response.status_code != 200:
                raise RuntimeError(
                    "failed to resolve e2e probe expectation "
                    f"{probe.name}: status={response.status_code}"
                )
            payload = response.json()
            resolved.append(
                Probe(
                    name=probe.name,
                    prompt=probe.prompt,
                    expected_route=str(payload["route_id"]),
                    expected_target_model=str(payload["target_model"]),
                    stream=probe.stream,
                )
            )
    return resolved


def summarize_results(results: list[CheckResult]) -> None:
    for result in results:
        status = "PASS" if result.ok else "FAIL"
        print(f"{status}\t{result.name}\t{result.detail}")
    if not all(result.ok for result in results):
        raise SystemExit(1)


def print_progress(line: str) -> None:
    print(line, flush=True)


def format_route_failure_detail(record: dict[str, Any]) -> str:
    return f"event={record.get('event')}, error_type={record.get('error_type')}"


def validate_nonstream_probe_response(
    *,
    probe: Probe,
    response: httpx.Response,
    expected_outer_model: str | None = "intentmux",
) -> list[CheckResult]:
    model = None
    if response.headers.get("content-type", "").startswith("application/json"):
        model = response.json().get("model")
    router_request_id = router_request_id_from_response(response)
    return [
        CheckResult(
            f"{probe.name}_status",
            response.status_code == 200,
            f"status={response.status_code}",
        ),
        CheckResult(
            f"{probe.name}_outer_model",
            expected_outer_model is None or model == expected_outer_model,
            f"model={model}, expected={expected_outer_model or 'any'}",
        ),
        CheckResult(
            f"{probe.name}_router_request_id",
            bool(router_request_id),
            f"request_id={router_request_id}",
        ),
    ]


def validate_streaming_probe_response(
    *,
    probe: Probe,
    response: httpx.Response,
    body_head: bytes,
    require_stream_done: bool = False,
) -> list[CheckResult]:
    starts_with_data = body_head.startswith(b"data:")
    has_done = b"data: [DONE]" in body_head
    router_request_id = router_request_id_from_response(response)
    results = [
        CheckResult(
            f"{probe.name}_status",
            response.status_code == 200,
            f"status={response.status_code}",
        ),
        CheckResult(
            f"{probe.name}_sse",
            starts_with_data,
            f"starts_with_data={starts_with_data}",
        ),
        CheckResult(
            f"{probe.name}_router_request_id",
            bool(router_request_id),
            f"request_id={router_request_id}",
        ),
    ]
    if require_stream_done:
        results.append(
            CheckResult(
                f"{probe.name}_stream_done",
                has_done,
                f"has_done={has_done}",
            )
        )
    return results


def read_bounded_stream_body(
    response: httpx.Response,
    *,
    max_chunks: int,
    max_bytes: int,
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


def router_request_id_from_response(response: httpx.Response) -> str | None:
    return (
        response.headers.get("x-router-request-id")
        or response.headers.get("llm_provider-x-router-request-id")
    )


def run_probe(
    *,
    client: httpx.Client,
    base_url: str,
    api_key: str,
    probe: Probe,
    request_id: str,
    expected_outer_model: str | None = "intentmux",
    require_stream_done: bool = False,
    stream_max_chunks: int = 200,
    stream_max_bytes: int = 262_144,
    max_probe_elapsed_ms: float | None = None,
) -> list[CheckResult]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "x-request-id": request_id,
    }
    payload = {
        "model": "intentmux",
        "metadata": {"semantic_router_request_id": request_id},
        "user": request_id,
        "messages": [{"role": "user", "content": probe.prompt}],
        "max_tokens": 8,
        "stream": probe.stream,
    }
    started = time.monotonic()
    if probe.stream:
        try:
            with client.stream(
                "POST",
                f"{base_url}/v1/chat/completions",
                headers=headers,
                json=payload,
            ) as response:
                body_head = read_bounded_stream_body(
                    response,
                    max_chunks=stream_max_chunks,
                    max_bytes=stream_max_bytes,
                )
                return validate_streaming_probe_response(
                    probe=probe,
                    response=response,
                    body_head=body_head,
                    require_stream_done=require_stream_done,
                ) + probe_elapsed_results(
                    probe=probe,
                    elapsed_ms=(time.monotonic() - started) * 1000,
                    max_probe_elapsed_ms=max_probe_elapsed_ms,
                )
        except httpx.HTTPError as exc:
            return [
                CheckResult(
                    f"{probe.name}_request",
                    False,
                    f"{type(exc).__name__}: {exc}",
                )
            ]

    try:
        response = client.post(
            f"{base_url}/v1/chat/completions",
            headers=headers,
            json=payload,
        )
    except httpx.HTTPError as exc:
        return [
            CheckResult(
                f"{probe.name}_request",
                False,
                f"{type(exc).__name__}: {exc}",
            )
        ]
    return validate_nonstream_probe_response(
        probe=probe,
        response=response,
        expected_outer_model=expected_outer_model,
    ) + probe_elapsed_results(
        probe=probe,
        elapsed_ms=(time.monotonic() - started) * 1000,
        max_probe_elapsed_ms=max_probe_elapsed_ms,
    )


def probe_elapsed_results(
    *,
    probe: Probe,
    elapsed_ms: float,
    max_probe_elapsed_ms: float | None,
) -> list[CheckResult]:
    if max_probe_elapsed_ms is None:
        return []
    return [
        CheckResult(
            f"{probe.name}_probe_elapsed",
            elapsed_ms <= max_probe_elapsed_ms,
            f"elapsed_ms={elapsed_ms:.2f}, max={max_probe_elapsed_ms}",
        )
    ]


def docker_logs(container: str, tail: int) -> str:
    completed = subprocess.run(
        ["docker", "logs", "--tail", str(tail), container],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return completed.stdout


RETRYABLE_AZURE_LOG_PATTERNS = (
    "connecttimeouterror",
    "connection to management.azure.com timed out",
    "max retries exceeded",
    "read timed out",
    "serviceunavailable",
    "gateway timeout",
    "temporarily unavailable",
    "too many requests",
    "http 429",
    "http 5",
)
NON_RETRYABLE_AZURE_LOG_PATTERNS = (
    "authorizationfailed",
    "forbidden",
    "invalidauthenticationtoken",
    "please run 'az login'",
    "resource not found",
    "resourcenotfound",
)


def azure_log_error_output(exc: BaseException) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        return str(exc.output or "")
    if isinstance(exc, subprocess.TimeoutExpired):
        output = exc.output or exc.stderr or ""
        if isinstance(output, bytes):
            return output.decode("utf-8", errors="replace")
        return str(output)
    return str(exc)


def retryable_azure_log_error(exc: BaseException) -> bool:
    if isinstance(exc, subprocess.TimeoutExpired):
        return True
    text = azure_log_error_output(exc).lower()
    if any(pattern in text for pattern in NON_RETRYABLE_AZURE_LOG_PATTERNS):
        return False
    return any(pattern in text for pattern in RETRYABLE_AZURE_LOG_PATTERNS)


def azure_containerapp_logs(name: str, resource_group: str, tail: int) -> str:
    command = [
        "az",
        "containerapp",
        "logs",
        "show",
        "--name",
        name,
        "--resource-group",
        resource_group,
        "--tail",
        str(tail),
    ]
    attempts = 3
    last_exc: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            completed = subprocess.run(
                command,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
            )
            return completed.stdout
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            last_exc = exc
            if attempt >= attempts or not retryable_azure_log_error(exc):
                break
            time.sleep(2.0 * (2 ** (attempt - 1)))
    assert last_exc is not None
    raise last_exc


def collect_logs(
    *,
    source: str,
    docker_container: str,
    azure_containerapp_name: str | None,
    azure_resource_group: str | None,
    tail: int,
) -> str:
    if source == "docker":
        return docker_logs(docker_container, tail)
    if source == "azure":
        if not azure_containerapp_name or not azure_resource_group:
            raise ValueError(
                "--azure-containerapp-name and --azure-resource-group are required "
                "when --log-source=azure"
            )
        return azure_containerapp_logs(azure_containerapp_name, azure_resource_group, tail)
    raise ValueError(f"unsupported log source: {source}")


def validate_route_logs(
    *,
    raw_logs: str,
    probes: list[tuple[Probe, str]],
    require_request_id_log_match: bool = False,
    max_route_duration_ms: float | None = None,
) -> list[CheckResult]:
    route_logs = parse_route_logs(raw_logs)
    results: list[CheckResult] = []
    used_indexes: set[int] = set()
    strict_request_id_matches = 0
    correlation_statuses: list[str] = []
    for probe, request_id in probes:
        record = find_route_log(route_logs, request_id=request_id, stream=probe.stream)
        matched_by = "request_id" if record is not None else "not_found"
        if record is None:
            matched = find_matching_route_log(
                route_logs,
                probe=probe,
                used_indexes=used_indexes,
            )
            if matched is not None:
                index, record = matched
                used_indexes.add(index)
                matched_by = "route_shape"
        if matched_by == "request_id":
            strict_request_id_matches += 1
        correlation_statuses.append(f"{probe.name}:{matched_by}")
        results.append(
            CheckResult(
                f"{probe.name}_route_log_present",
                record is not None,
                f"request_id={request_id}, matched_by={matched_by}",
            )
        )
        if record is None:
            continue
        if record.get("event") != "route_complete":
            results.append(
                CheckResult(
                    f"{probe.name}_route_completed",
                    False,
                    format_route_failure_detail(record),
                )
            )
            continue
        results.extend(
            [
                CheckResult(
                    f"{probe.name}_source_model",
                    record.get("source_model") == "intentmux",
                    f"source_model={record.get('source_model')}",
                ),
                CheckResult(
                    f"{probe.name}_route_id",
                    record.get("route_id") == probe.expected_route,
                    f"route_id={record.get('route_id')}",
                ),
                CheckResult(
                    f"{probe.name}_target_model",
                    record.get("target_model") == probe.expected_target_model,
                    f"target_model={record.get('target_model')}",
                ),
                CheckResult(
                    f"{probe.name}_upstream_status",
                    record.get("upstream_status") == 200,
                    f"upstream_status={record.get('upstream_status')}",
                ),
            ]
        )
        if max_route_duration_ms is not None:
            duration_ms = record.get("duration_ms")
            duration_ok = not isinstance(duration_ms, int | float) or duration_ms <= max_route_duration_ms
            results.append(
                CheckResult(
                    f"{probe.name}_route_duration",
                    duration_ok,
                    f"duration_ms={duration_ms or 'unavailable'}, max={max_route_duration_ms}",
                )
            )
    secret_or_prompt_leak = "Bearer " in raw_logs or any(
        probe.prompt in raw_logs for probe, _request_id in probes
    )
    total_probes = len(probes)
    all_strict = strict_request_id_matches == total_probes
    results.append(
        CheckResult(
            "route_log_match_mode",
            all_strict or not require_request_id_log_match,
            (
                f"strict_request_id_matches={strict_request_id_matches}/{total_probes}, "
                f"require_request_id_log_match={require_request_id_log_match}, "
                f"per_probe={','.join(correlation_statuses)}"
            ),
        )
    )
    results.append(
        CheckResult(
            "log_redaction",
            not secret_or_prompt_leak,
            "no prompt or bearer token in sidecar logs",
        )
    )
    return results


def probe_request_succeeded(probe: Probe, results: list[CheckResult]) -> bool:
    return any(result.name == f"{probe.name}_status" and result.ok for result in results)


def router_request_id_from_results(probe: Probe, results: list[CheckResult]) -> str | None:
    expected_name = f"{probe.name}_router_request_id"
    for result in results:
        if result.name == expected_name and result.ok:
            prefix = "request_id="
            if result.detail.startswith(prefix):
                return result.detail[len(prefix) :]
    return None


def run_e2e(
    *,
    litellm_base_url: str,
    api_key: str,
    timeout: float,
    log_container: str,
    log_source: str = "docker",
    log_tail: int,
    skip_log_check: bool,
    require_request_id_log_match: bool,
    azure_containerapp_name: str | None = None,
    azure_resource_group: str | None = None,
    expected_outer_model: str | None = "intentmux",
    require_stream_done: bool = False,
    stream_max_chunks: int = 200,
    stream_max_bytes: int = 262_144,
    max_probe_elapsed_ms: float | None = None,
    max_route_duration_ms: float | None = None,
    probes: Sequence[Probe] = DEFAULT_PROBES,
    progress: Callable[[str], None] | None = None,
) -> list[CheckResult]:
    base_url = litellm_base_url.rstrip("/")
    probes_with_ids = [
        (probe, f"intentmux-e2e-{probe.name}-{uuid.uuid4().hex[:12]}")
        for probe in probes
    ]
    results: list[CheckResult] = []
    successful_probes_with_ids: list[tuple[Probe, str]] = []
    failed_probes_with_ids: list[tuple[Probe, str]] = []
    with httpx.Client(timeout=timeout) as client:
        for probe, request_id in probes_with_ids:
            if progress is not None:
                progress(f"RUN\t{probe.name}\trequest_id={request_id}")
            probe_results = run_probe(
                client=client,
                base_url=base_url,
                api_key=api_key,
                probe=probe,
                request_id=request_id,
                expected_outer_model=expected_outer_model,
                require_stream_done=require_stream_done,
                stream_max_chunks=stream_max_chunks,
                stream_max_bytes=stream_max_bytes,
                max_probe_elapsed_ms=max_probe_elapsed_ms,
            )
            results.extend(probe_results)
            if probe_request_succeeded(probe, probe_results):
                successful_probes_with_ids.append(
                    (probe, router_request_id_from_results(probe, probe_results) or request_id)
                )
            else:
                failed_probes_with_ids.append((probe, request_id))

    if not skip_log_check:
        for probe, request_id in failed_probes_with_ids:
            results.append(
                CheckResult(
                    f"{probe.name}_route_log_present",
                    False,
                    f"request_id={request_id}, skipped_due_to_failed_probe",
                )
            )
        results.extend(
            validate_route_logs(
                raw_logs=collect_logs(
                    source=log_source,
                    docker_container=log_container,
                    azure_containerapp_name=azure_containerapp_name,
                    azure_resource_group=azure_resource_group,
                    tail=log_tail,
                ),
                probes=successful_probes_with_ids,
                require_request_id_log_match=require_request_id_log_match,
                max_route_duration_ms=max_route_duration_ms,
            )
        )
    return results


def apply_target_model_overrides(
    probes: Sequence[Probe],
    *,
    lite_target_model: str | None,
    deep_target_model: str | None,
) -> list[Probe]:
    overrides = {
        route_id: target
        for route_id, target in (
            ("lite", lite_target_model),
            ("deep", deep_target_model),
        )
        if target
    }
    return [
        Probe(
            name=probe.name,
            prompt=probe.prompt,
            expected_route=probe.expected_route,
            expected_target_model=overrides.get(
                probe.expected_route, probe.expected_target_model
            ),
            stream=probe.stream,
        )
        for probe in probes
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--litellm-base-url",
        default=os.getenv("LITELLM_BASE_URL", "http://127.0.0.1:4000"),
    )
    parser.add_argument("--api-key", default=os.getenv("LITELLM_MASTER_KEY"))
    parser.add_argument("--timeout", type=float, default=150.0)
    parser.add_argument("--log-container", default="intentmux")
    parser.add_argument(
        "--log-source",
        choices=("docker", "azure"),
        default=os.getenv("INTENTMUX_E2E_LOG_SOURCE", "docker"),
    )
    parser.add_argument("--azure-containerapp-name", default=os.getenv("AZURE_CONTAINERAPP_NAME"))
    parser.add_argument("--azure-resource-group", default=os.getenv("AZURE_RESOURCE_GROUP"))
    parser.add_argument("--log-tail", type=int, default=300)
    parser.add_argument(
        "--router-base-url",
        default=os.getenv("INTENTMUX_ROUTER_BASE_URL"),
        help=(
            "Optional IntentMux base URL. When set, E2E first resolves expected "
            "route_id and target_model from /v1/intentmux/decision."
        ),
    )
    parser.add_argument(
        "--intentmux-api-key",
        default=os.getenv("ROUTER_INBOUND_API_KEY") or os.getenv("INTENTMUX_API_KEY"),
        help="Optional IntentMux inbound API key for expectation resolution.",
    )
    parser.add_argument("--skip-log-check", action="store_true")
    parser.add_argument("--require-request-id-log-match", action="store_true")
    parser.add_argument("--expected-lite-target-model")
    parser.add_argument("--expected-deep-target-model")
    parser.add_argument(
        "--skip-outer-model-check",
        action="store_true",
        help="Allow LiteLLM to return the final provider model name instead of intentmux.",
    )
    parser.add_argument("--require-stream-done", action="store_true")
    parser.add_argument("--stream-max-chunks", type=int, default=200)
    parser.add_argument("--stream-max-bytes", type=int, default=262_144)
    parser.add_argument("--max-probe-elapsed-ms", type=float)
    parser.add_argument("--max-route-duration-ms", type=float)
    parser.add_argument("--quiet-progress", action="store_true")
    args = parser.parse_args()

    if not args.api_key:
        raise SystemExit("LITELLM_MASTER_KEY or --api-key is required")
    probes = DEFAULT_PROBES
    if args.router_base_url:
        probes = resolve_probe_expectations(
            DEFAULT_PROBES,
            router_base_url=args.router_base_url,
            intentmux_api_key=args.intentmux_api_key,
            timeout=args.timeout,
        )
    probes = apply_target_model_overrides(
        probes,
        lite_target_model=args.expected_lite_target_model,
        deep_target_model=args.expected_deep_target_model,
    )
    summarize_results(
        run_e2e(
            litellm_base_url=args.litellm_base_url,
            api_key=args.api_key,
            timeout=args.timeout,
            log_container=args.log_container,
            log_source=args.log_source,
            log_tail=args.log_tail,
            skip_log_check=args.skip_log_check,
            require_request_id_log_match=args.require_request_id_log_match,
            azure_containerapp_name=args.azure_containerapp_name,
            azure_resource_group=args.azure_resource_group,
            expected_outer_model=None if args.skip_outer_model_check else "intentmux",
            require_stream_done=args.require_stream_done,
            stream_max_chunks=args.stream_max_chunks,
            stream_max_bytes=args.stream_max_bytes,
            max_probe_elapsed_ms=args.max_probe_elapsed_ms,
            max_route_duration_ms=args.max_route_duration_ms,
            probes=probes,
            progress=None if args.quiet_progress else print_progress,
        )
    )


if __name__ == "__main__":
    main()
