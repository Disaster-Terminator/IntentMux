from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "intentmux.ai_review_summary.v1"
ALLOWED_DECISIONS = {
    "route_ok",
    "suspected_misroute",
    "needs_human",
    "privacy_blocked",
    "watch_only",
}
ALLOWED_CONFIDENCE = {"high", "medium", "low"}
ALLOWED_ROUTES = {"lite", "deep", "unknown"}
RAW_PROMPT_KEYS = {
    "latest_user_text",
    "prompt",
    "messages",
    "completion",
    "request_body",
}


class ReviewResultError(ValueError):
    pass


def summarize_review_result(result: dict[str, Any]) -> dict[str, Any]:
    items = result.get("items")
    if not isinstance(items, list):
        raise ReviewResultError("items must be a list")

    normalized_items = [normalize_item(item, index) for index, item in enumerate(items, start=1)]
    decision_counts = Counter(item["agent_decision"] for item in normalized_items)
    confidence_counts = Counter(item["confidence"] for item in normalized_items)
    route_counts = Counter(item["suggested_expected_route"] for item in normalized_items)

    human_audit_items = [
        item
        for item in normalized_items
        if item["human_decision_required"] or item["agent_decision"] in {"needs_human", "privacy_blocked"}
    ]
    suspected_regression_cases = [
        item for item in normalized_items if item["agent_decision"] == "suspected_misroute"
    ]
    privacy_blocked_cases = [
        item
        for item in normalized_items
        if item["agent_decision"] == "privacy_blocked" or item["redaction_required"]
    ]

    return {
        "schema_version": SCHEMA_VERSION,
        "source_schema_version": result.get("schema_version"),
        "summary": {
            "item_count": len(normalized_items),
            "decision_counts": dict(sorted(decision_counts.items())),
            "confidence_counts": dict(sorted(confidence_counts.items())),
            "suggested_route_counts": dict(sorted(route_counts.items())),
            "human_audit_count": len(human_audit_items),
            "suspected_regression_count": len(suspected_regression_cases),
            "privacy_blocked_count": len(privacy_blocked_cases),
        },
        "human_audit_items": human_audit_items,
        "suspected_regression_cases": suspected_regression_cases,
        "privacy_blocked_cases": privacy_blocked_cases,
        "items": normalized_items,
    }


def normalize_item(item: Any, index: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ReviewResultError(f"item {index}: must be an object")
    raw_keys = sorted(RAW_PROMPT_KEYS.intersection(item))
    if raw_keys:
        raise ReviewResultError(f"item {index}: raw prompt fields are not allowed: {', '.join(raw_keys)}")

    request_id = item.get("request_id")
    if not isinstance(request_id, str) or not request_id:
        raise ReviewResultError(f"item {index}: request_id must be a non-empty string")

    agent_decision = item.get("agent_decision")
    if agent_decision not in ALLOWED_DECISIONS:
        raise ReviewResultError(f"item {index}: agent_decision must be one of {sorted(ALLOWED_DECISIONS)}")

    confidence = item.get("confidence")
    if confidence not in ALLOWED_CONFIDENCE:
        raise ReviewResultError(f"item {index}: confidence must be one of {sorted(ALLOWED_CONFIDENCE)}")

    suggested_expected_route = item.get("suggested_expected_route")
    if suggested_expected_route not in ALLOWED_ROUTES:
        raise ReviewResultError(f"item {index}: suggested_expected_route must be lite, deep, or unknown")

    summary_zh = item.get("summary_zh")
    if not isinstance(summary_zh, str) or not summary_zh:
        raise ReviewResultError(f"item {index}: summary_zh must be a non-empty string")

    evidence = item.get("evidence")
    if not isinstance(evidence, list) or any(not isinstance(value, str) for value in evidence):
        raise ReviewResultError(f"item {index}: evidence must be a list of strings")

    return {
        "request_id": request_id,
        "agent_decision": agent_decision,
        "confidence": confidence,
        "suggested_expected_route": suggested_expected_route,
        "summary_zh": summary_zh,
        "evidence": evidence,
        "human_decision_required": bool(item.get("human_decision_required")),
        "redaction_required": bool(item.get("redaction_required")),
    }


def render_markdown(summary: dict[str, Any]) -> str:
    data = summary.get("summary", {})
    lines = [
        "# IntentMux AI Review Summary",
        "",
        "## Summary",
        f"- schema_version: {summary.get('schema_version')}",
        f"- item_count: {data.get('item_count', 0) if isinstance(data, dict) else 0}",
        f"- decision_counts: {format_counts(data.get('decision_counts', {})) if isinstance(data, dict) else 'none'}",
        f"- confidence_counts: {format_counts(data.get('confidence_counts', {})) if isinstance(data, dict) else 'none'}",
        f"- suggested_route_counts: {format_counts(data.get('suggested_route_counts', {})) if isinstance(data, dict) else 'none'}",
        "",
    ]
    append_items(lines, "Human Audit Items", summary.get("human_audit_items", []))
    append_items(lines, "Suspected Regression Cases", summary.get("suspected_regression_cases", []))
    append_items(lines, "Privacy Blocked Cases", summary.get("privacy_blocked_cases", []))
    lines.extend(
        [
            "## Privacy Boundary",
            "",
            "This summary must not contain raw prompts, completions, request bodies, tokens, or bearer credentials.",
        ]
    )
    return "\n".join(lines) + "\n"


def append_items(lines: list[str], title: str, items: Any) -> None:
    lines.extend([f"## {title}", ""])
    if not isinstance(items, list) or not items:
        lines.extend(["none", ""])
        return
    lines.extend(
        [
            "| request_id | decision | confidence | suggested_route | human_decision_required | redaction_required | summary_zh | evidence |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for item in items:
        lines.append(
            "| "
            + " | ".join(
                [
                    markdown_cell(item.get("request_id")),
                    markdown_cell(item.get("agent_decision")),
                    markdown_cell(item.get("confidence")),
                    markdown_cell(item.get("suggested_expected_route")),
                    markdown_cell(item.get("human_decision_required")),
                    markdown_cell(item.get("redaction_required")),
                    markdown_cell(item.get("summary_zh")),
                    markdown_cell("; ".join(item.get("evidence") or [])),
                ]
            )
            + " |"
        )
    lines.append("")


def format_counts(counts: Any) -> str:
    if not isinstance(counts, dict) or not counts:
        return "none"
    return ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))


def markdown_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and summarize IntentMux AI review results.")
    parser.add_argument("--input", required=True, help="AI review result JSON.")
    parser.add_argument("--json-output", required=True)
    parser.add_argument("--markdown-output", required=True)
    args = parser.parse_args()

    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ReviewResultError("input JSON must be an object")
    summary = summarize_review_result(payload)

    json_output = Path(args.json_output)
    json_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    markdown_output = Path(args.markdown_output)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.write_text(render_markdown(summary), encoding="utf-8")


if __name__ == "__main__":
    main()
