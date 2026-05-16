from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
import subprocess
import uuid
from collections.abc import Callable
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
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("event") in {"route_complete", "route_error"}:
            records.append(record)
    return records


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
            and record.get("source_model") == "semantic-router"
            and record.get("route_id") == probe.expected_route
            and record.get("target_model") == probe.expected_target_model
            and record.get("stream") is probe.stream
            and record.get("upstream_status") == 200
        ):
            return index, record
    return None


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
    *, probe: Probe, response: httpx.Response
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
            model == "semantic-router",
            f"model={model}",
        ),
        CheckResult(
            f"{probe.name}_router_request_id",
            bool(router_request_id),
            f"request_id={router_request_id}",
        ),
    ]


def validate_streaming_probe_response(
    *, probe: Probe, response: httpx.Response, first_chunk: bytes
) -> list[CheckResult]:
    starts_with_data = first_chunk.startswith(b"data:")
    router_request_id = router_request_id_from_response(response)
    return [
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
) -> list[CheckResult]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "x-request-id": request_id,
    }
    payload = {
        "model": "semantic-router",
        "metadata": {"semantic_router_request_id": request_id},
        "user": request_id,
        "messages": [{"role": "user", "content": probe.prompt}],
        "max_tokens": 8,
        "stream": probe.stream,
    }
    if probe.stream:
        try:
            with client.stream(
                "POST",
                f"{base_url}/v1/chat/completions",
                headers=headers,
                json=payload,
            ) as response:
                first_chunk = next(response.iter_bytes(), b"")
                return validate_streaming_probe_response(
                    probe=probe,
                    response=response,
                    first_chunk=first_chunk,
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
    return validate_nonstream_probe_response(probe=probe, response=response)


def docker_logs(container: str, tail: int) -> str:
    completed = subprocess.run(
        ["docker", "logs", "--tail", str(tail), container],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return completed.stdout


def validate_route_logs(
    *,
    raw_logs: str,
    probes: list[tuple[Probe, str]],
    require_request_id_log_match: bool = False,
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
                    record.get("source_model") == "semantic-router",
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
    log_tail: int,
    skip_log_check: bool,
    require_request_id_log_match: bool,
    progress: Callable[[str], None] | None = None,
) -> list[CheckResult]:
    base_url = litellm_base_url.rstrip("/")
    probes_with_ids = [
        (probe, f"semantic-e2e-{probe.name}-{uuid.uuid4().hex[:12]}")
        for probe in DEFAULT_PROBES
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
                raw_logs=docker_logs(log_container, log_tail),
                probes=successful_probes_with_ids,
                require_request_id_log_match=require_request_id_log_match,
            )
        )
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--litellm-base-url",
        default=os.getenv("LITELLM_BASE_URL", "http://127.0.0.1:4000"),
    )
    parser.add_argument("--api-key", default=os.getenv("LITELLM_MASTER_KEY"))
    parser.add_argument("--timeout", type=float, default=150.0)
    parser.add_argument("--log-container", default="intentmux")
    parser.add_argument("--log-tail", type=int, default=300)
    parser.add_argument("--skip-log-check", action="store_true")
    parser.add_argument("--require-request-id-log-match", action="store_true")
    parser.add_argument("--quiet-progress", action="store_true")
    args = parser.parse_args()

    if not args.api_key:
        raise SystemExit("LITELLM_MASTER_KEY or --api-key is required")
    summarize_results(
        run_e2e(
            litellm_base_url=args.litellm_base_url,
            api_key=args.api_key,
            timeout=args.timeout,
            log_container=args.log_container,
            log_tail=args.log_tail,
            skip_log_check=args.skip_log_check,
            require_request_id_log_match=args.require_request_id_log_match,
            progress=None if args.quiet_progress else print_progress,
        )
    )


if __name__ == "__main__":
    main()
