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
    expected_target: str | None


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
        expected_target=raw.get("expected_target"),
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
    target_model: str,
    expected_target: str | None,
    reason: str,
) -> list[str]:
    if expected_target is None:
        status = "N/A"
    else:
        status = "PASS" if target_model == expected_target else "FAIL"
    return [status, case_name, target_model, expected_target or "", reason]


def _print_table(rows: list[list[str]]) -> None:
    headers = ["status", "case", "selected_target", "expected_target", "reason"]
    table = [headers] + rows
    widths = [max(len(str(row[i])) for row in table) for i in range(len(headers))]

    def render(row: list[str]) -> str:
        return " | ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row))

    print(render(headers))
    print("-+-".join("-" * width for width in widths))
    for row in rows:
        print(render(row))


def call_decision_endpoint(endpoint: str, payload: dict[str, Any], timeout_s: float) -> dict[str, Any]:
    req = request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout_s) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"decision endpoint returned {exc.code}: {body}") from exc


def run_review(endpoint: str, cases_path: Path, timeout_s: float) -> int:
    rows: list[list[str]] = []
    mismatch_count = 0

    for case in load_cases(cases_path):
        result = call_decision_endpoint(endpoint, case.payload, timeout_s)
        row = format_result_row(
            case_name=case.name,
            target_model=str(result.get("target_model", "")),
            expected_target=case.expected_target,
            reason=str(result.get("reason", "")),
        )
        rows.append(row)
        if row[0] == "FAIL":
            mismatch_count += 1

    _print_table(rows)
    print(f"\nTotal cases: {len(rows)}; mismatches: {mismatch_count}")
    return 1 if mismatch_count else 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default="http://127.0.0.1:8080/v1/semantic-router/decision")
    parser.add_argument("--cases", default="tests/samples/review_decisions.yaml")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()

    raise SystemExit(run_review(args.endpoint, Path(args.cases), args.timeout))


if __name__ == "__main__":
    main()
