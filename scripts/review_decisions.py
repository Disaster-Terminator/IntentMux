from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, request

import yaml

DEFAULT_ROUTE_MODEL = "semantic-router"


@dataclass(frozen=True)
class ReviewCase:
    name: str
    payload: dict[str, Any]
    expected_route: str | None


def _normalize_case(raw: dict[str, Any], source: str) -> ReviewCase:
    if "name" not in raw:
        raise ValueError(f"{source}: missing required field 'name'")

    has_text = "text" in raw
    has_messages = "messages" in raw
    if has_text == has_messages:
        raise ValueError(f"{source}: provide exactly one of 'text' or 'messages'")

    if has_text:
        payload = {"messages": [{"role": "user", "content": raw["text"]}]}
    else:
        payload = {"messages": raw["messages"]}

    payload["model"] = raw.get("model", DEFAULT_ROUTE_MODEL)

    return ReviewCase(
        name=str(raw["name"]),
        payload=payload,
        expected_route=raw.get("expected_route"),
    )


def load_cases(path: Path) -> list[ReviewCase]:
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        cases: list[ReviewCase] = []
        for idx, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            cases.append(_normalize_case(json.loads(line), f"{path}:{idx}"))
        return cases

    if suffix in {".yaml", ".yml"}:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            items = raw.get("cases", [])
        else:
            items = raw
        return [_normalize_case(item, str(path)) for item in items]

    raise ValueError("unsupported case format; use .jsonl, .yaml, or .yml")


def format_result_row(
    *,
    case_name: str,
    route_id: str,
    expected_route: str | None,
    reason: str,
) -> list[str]:
    if expected_route is None:
        status = "N/A"
    else:
        status = "PASS" if route_id == expected_route else "FAIL"
    return [status, case_name, route_id, expected_route or "", reason]


def _print_table(rows: list[list[str]]) -> None:
    headers = ["status", "case", "selected_route", "expected_route", "reason"]
    table = [headers] + rows
    widths = [max(len(str(row[i])) for row in table) for i in range(len(headers))]

    def render(row: list[str]) -> str:
        return " | ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row))

    print(render(headers))
    print("-+-".join("-" * width for width in widths))
    for row in rows:
        print(render(row))


def _status_for(expected_route: str | None, actual_route: str) -> str | None:
    if expected_route is None:
        return None
    return "pass" if actual_route == expected_route else "fail"


def _build_json_result(case: ReviewCase, decision_result: dict[str, Any]) -> dict[str, Any]:
    actual_route = str(decision_result.get("route_id") or decision_result.get("target_model", ""))
    output = {
        "case": case.name,
        "expected_route": case.expected_route,
        "actual_route": actual_route,
        "target_model": decision_result.get("target_model"),
        "status": _status_for(case.expected_route, actual_route),
        "reason": str(decision_result.get("reason", "")),
        "request_payload_model": str(case.payload.get("model", "")),
    }
    for key in ("score", "scores", "semantic_score", "rule_score"):
        if key in decision_result:
            output[key] = decision_result[key]
    return output


def _safe_error_message(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, error.HTTPError):
        return "http_error", f"decision endpoint returned HTTP {exc.code}"
    if isinstance(exc, error.URLError):
        reason = getattr(exc, "reason", "unknown")
        return "url_error", f"decision endpoint request failed: {reason}"
    return "request_error", f"decision endpoint request failed: {exc.__class__.__name__}"


def _build_error_json_result(case: ReviewCase, exc: Exception) -> dict[str, Any]:
    error_type, error_message = _safe_error_message(exc)
    return {
        "case": case.name,
        "expected_route": case.expected_route,
        "actual_route": None,
        "target_model": None,
        "status": "error",
        "reason": "",
        "error_type": error_type,
        "error_message": error_message,
        "request_payload_model": str(case.payload.get("model", "")),
    }


def call_decision_endpoint(endpoint: str, payload: dict[str, Any], timeout_s: float) -> dict[str, Any]:
    req = request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run_review(endpoint: str, cases_path: Path, timeout_s: float, output: str = "table") -> int:
    rows: list[list[str]] = []
    json_rows: list[dict[str, Any]] = []
    mismatch_count = 0
    endpoint_error_count = 0

    for case in load_cases(cases_path):
        try:
            result = call_decision_endpoint(endpoint, case.payload, timeout_s)
        except Exception as exc:
            endpoint_error_count += 1
            _, error_message = _safe_error_message(exc)
            rows.append(["ERROR", case.name, "", case.expected_route or "", error_message])
            json_rows.append(_build_error_json_result(case, exc))
            continue

        row = format_result_row(
            case_name=case.name,
            route_id=str(result.get("route_id") or result.get("target_model", "")),
            expected_route=case.expected_route,
            reason=str(result.get("reason", "")),
        )
        rows.append(row)
        json_rows.append(_build_json_result(case, result))
        if row[0] == "FAIL":
            mismatch_count += 1

    if output == "json":
        print(json.dumps(json_rows, ensure_ascii=False, indent=2))
    else:
        _print_table(rows)
        print(
            f"\nTotal cases: {len(rows)}; mismatches: {mismatch_count}; endpoint_errors: {endpoint_error_count}"
        )
    return 1 if (mismatch_count or endpoint_error_count) else 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default="http://127.0.0.1:8080/v1/semantic-router/decision")
    parser.add_argument("--cases", default="tests/samples/review_decisions.yaml")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--output", choices=["table", "json"], default="table")
    args = parser.parse_args()

    raise SystemExit(run_review(args.endpoint, Path(args.cases), args.timeout, output=args.output))


if __name__ == "__main__":
    main()
