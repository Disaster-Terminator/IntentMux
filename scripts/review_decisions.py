from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml


@dataclass(frozen=True)
class ReviewCase:
    name: str
    expected_target: str | None = None
    text: str | None = None
    messages: list[dict[str, Any]] | None = None

    def to_payload(self, model: str) -> dict[str, Any]:
        if self.text is None and self.messages is None:
            raise ValueError(f"case '{self.name}' must define either text or messages")
        payload: dict[str, Any] = {"model": model}
        if self.messages is not None:
            payload["messages"] = self.messages
        else:
            payload["messages"] = [{"role": "user", "content": self.text}]
        return payload


def load_cases(path: Path) -> list[ReviewCase]:
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        cases: list[ReviewCase] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            cases.append(ReviewCase(**json.loads(line)))
        return cases

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "cases" in raw:
        raw_cases = raw["cases"]
    else:
        raw_cases = raw
    return [ReviewCase(**item) for item in raw_cases]


def format_result_row(
    case_name: str,
    selected: str,
    expected: str | None,
    reason: str,
) -> str:
    status = "PASS" if expected is not None and selected == expected else "FAIL" if expected else "-"
    expected_str = expected or ""
    return f"{status}\t{case_name}\t{selected}\t{expected_str}\t{reason}"


def run_review(endpoint: str, model: str, cases: list[ReviewCase], timeout: float) -> int:
    print("STATUS\tCASE\tSELECTED\tEXPECTED\tREASON")
    mismatches = 0
    with httpx.Client(timeout=timeout) as client:
        for case in cases:
            response = client.post(endpoint, json=case.to_payload(model))
            response.raise_for_status()
            body = response.json()
            selected = body["target_model"]
            reason = body.get("reason", "")
            print(format_result_row(case.name, selected, case.expected_target, reason))
            if case.expected_target and selected != case.expected_target:
                mismatches += 1
    return 1 if mismatches else 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--model", default="semantic-router")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    endpoint = f"{args.base_url.rstrip('/')}/v1/semantic-router/decision"
    cases = load_cases(Path(args.cases))
    raise SystemExit(run_review(endpoint, args.model, cases, args.timeout))


if __name__ == "__main__":
    main()
