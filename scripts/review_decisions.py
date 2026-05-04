from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, request

import yaml


@dataclass(frozen=True)
class ReviewCase:
    name: str
    text: str | None = None
    messages: list[dict[str, Any]] | None = None
    expected_target: str | None = None


@dataclass(frozen=True)
class ReviewResult:
    case_name: str
    selected_target: str
    expected_target: str | None
    reason: str

    @property
    def status(self) -> str:
        if self.expected_target is None:
            return "N/A"
        return "PASS" if self.selected_target == self.expected_target else "FAIL"


def _normalize_case(raw: dict[str, Any]) -> ReviewCase:
    if "name" not in raw:
        raise ValueError("missing required field: name")
    if "text" not in raw and "messages" not in raw:
        raise ValueError("case must contain either text or messages")
    return ReviewCase(
        name=str(raw["name"]),
        text=raw.get("text"),
        messages=raw.get("messages"),
        expected_target=raw.get("expected_target"),
    )


def load_cases(path: Path) -> list[ReviewCase]:
    if path.suffix == ".jsonl":
        items = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    else:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict) and "cases" in loaded:
            items = loaded["cases"]
        elif isinstance(loaded, list):
            items = loaded
        else:
            raise ValueError("yaml must be a list or object with a 'cases' key")
    return [_normalize_case(item) for item in items]


def _build_payload(case: ReviewCase, route_model: str) -> dict[str, Any]:
    if case.messages is not None:
        messages = case.messages
    else:
        messages = [{"role": "user", "content": case.text or ""}]
    return {"model": route_model, "messages": messages}


def call_decision_endpoint(base_url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    endpoint = f"{base_url.rstrip('/')}/v1/semantic-router/decision"
    req = request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def format_result_line(result: ReviewResult) -> str:
    expected = result.expected_target or "-"
    return (
        f"{result.status}\t{result.case_name}\t{result.selected_target}\t"
        f"{expected}\t{result.reason}"
    )


def run_review(cases: list[ReviewCase], base_url: str, route_model: str, timeout: float) -> int:
    failures = 0
    print("STATUS\tCASE\tSELECTED\tEXPECTED\tREASON")
    for case in cases:
        payload = _build_payload(case, route_model)
        response = call_decision_endpoint(base_url, payload, timeout)
        result = ReviewResult(
            case_name=case.name,
            selected_target=str(response.get("target_model", "")),
            expected_target=case.expected_target,
            reason=str(response.get("reason", "")),
        )
        print(format_result_line(result))
        if result.status == "FAIL":
            failures += 1
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline review helper for semantic router decisions")
    parser.add_argument("--cases", required=True, help="Path to YAML or JSONL review cases")
    parser.add_argument("--base-url", default="http://127.0.0.1:8787")
    parser.add_argument("--route-model", default="semantic-router")
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()

    try:
        code = run_review(
            cases=load_cases(Path(args.cases)),
            base_url=args.base_url,
            route_model=args.route_model,
            timeout=args.timeout,
        )
    except (ValueError, OSError, json.JSONDecodeError, error.URLError) as exc:
        print(f"ERROR\t{exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    raise SystemExit(code)


if __name__ == "__main__":
    main()
