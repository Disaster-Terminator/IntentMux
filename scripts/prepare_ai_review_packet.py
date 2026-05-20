from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.select_review_candidates import expand_log_paths, load_prompt_review_records  # noqa: E402

SCHEMA_VERSION = "intentmux.ai_review_packet.v1"
ALLOWED_PROMPT_TEXT_MODES = {"off", "raw_local"}
GROUPS = (
    "needs_human_decision",
    "likely_regression_case",
    "watch_only",
    "privacy_blocked",
)


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("input JSON must be an object")
    return payload


def prompt_text_index(prompt_records: Iterable[dict[str, Any]]) -> dict[str, str]:
    indexed: dict[str, str] = {}
    for record in prompt_records:
        if record.get("event") != "prompt_review":
            continue
        request_id = record.get("request_id")
        latest_user_text = record.get("latest_user_text")
        if isinstance(request_id, str) and isinstance(latest_user_text, str):
            indexed[request_id] = latest_user_text
    return indexed


def group_candidate(candidate: dict[str, Any]) -> str:
    review_reasons = set(candidate.get("review_reasons") or [])
    reason = candidate.get("reason")
    prompt_review = candidate.get("prompt_review")

    if "hard_rule" in review_reasons:
        return "needs_human_decision"
    if review_reasons.intersection({"route_error", "upstream_non_2xx", "embedding_error"}):
        return "needs_human_decision"
    if isinstance(reason, str) and reason.startswith("hard_rule:"):
        return "needs_human_decision"
    if isinstance(prompt_review, dict) and prompt_review.get("truncated") is True:
        return "privacy_blocked"
    if review_reasons.intersection({"low_confidence", "near_margin", "near_threshold"}):
        if isinstance(prompt_review, dict) and prompt_review.get("matched") is True:
            return "likely_regression_case"
        return "watch_only"
    return "watch_only"


def build_ai_review_packet(
    candidate_report: dict[str, Any],
    *,
    prompt_records: Iterable[dict[str, Any]] | None = None,
    include_prompt_text: str = "off",
    max_prompt_chars: int = 2000,
) -> dict[str, Any]:
    if include_prompt_text not in ALLOWED_PROMPT_TEXT_MODES:
        raise ValueError("include_prompt_text must be 'off' or 'raw_local'")

    prompt_texts = prompt_text_index(prompt_records or [])
    packet_candidates: list[dict[str, Any]] = []
    group_counts: Counter[str] = Counter({group: 0 for group in GROUPS})

    for candidate in candidate_report.get("candidates", []):
        if not isinstance(candidate, dict):
            continue
        group = group_candidate(candidate)
        group_counts[group] += 1
        request_id = candidate.get("request_id")
        prompt_excerpt = None
        if include_prompt_text == "raw_local" and isinstance(request_id, str):
            text = prompt_texts.get(request_id)
            if text is not None:
                prompt_excerpt = text[:max(max_prompt_chars, 0)]

        packet_candidates.append(
            {
                "group": group,
                "request_id": request_id,
                "timestamp": candidate.get("timestamp"),
                "route_id": candidate.get("route_id"),
                "target_model": candidate.get("target_model"),
                "reason": candidate.get("reason"),
                "review_reasons": list(candidate.get("review_reasons") or []),
                "score": candidate.get("score"),
                "second_score": candidate.get("second_score"),
                "score_margin": candidate.get("score_margin"),
                "threshold": candidate.get("threshold"),
                "margin": candidate.get("margin"),
                "top_route_id": candidate.get("top_route_id"),
                "second_route_id": candidate.get("second_route_id"),
                "match_source": candidate.get("match_source"),
                "match_index": candidate.get("match_index"),
                "match_text_sha256": candidate.get("match_text_sha256"),
                "match_score": candidate.get("match_score"),
                "match_provenance": candidate.get("match_provenance"),
                "duration_ms": candidate.get("duration_ms"),
                "upstream_status": candidate.get("upstream_status"),
                "format_signals": candidate.get("format_signals") if isinstance(candidate.get("format_signals"), dict) else {},
                "prompt_review": candidate.get("prompt_review") if isinstance(candidate.get("prompt_review"), dict) else None,
                "prompt_excerpt": prompt_excerpt,
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "privacy_mode": "raw_local" if include_prompt_text == "raw_local" else "metadata_only",
        "instructions": {
            "language": "zh-CN",
            "task": "Review IntentMux route candidates and summarize only actionable routing-quality findings.",
            "rules": [
                "Do not invent route labels.",
                "Escalate uncertainty instead of guessing.",
                "Do not suggest production policy changes without evidence.",
                "Return structured JSON matching intentmux.ai_review_result.v1.",
            ],
        },
        "summary": {
            "candidate_count": len(packet_candidates),
            "groups": {group: group_counts[group] for group in GROUPS},
            "source_candidate_count": candidate_report.get("summary", {}).get("candidate_count"),
        },
        "candidates": packet_candidates,
    }


def render_markdown(packet: dict[str, Any]) -> str:
    summary = packet.get("summary", {})
    groups = summary.get("groups", {}) if isinstance(summary, dict) else {}
    lines = [
        "# IntentMux AI Review Packet",
        "",
        "## Summary",
        f"- schema_version: {packet.get('schema_version')}",
        f"- privacy_mode: {packet.get('privacy_mode')}",
        f"- candidate_count: {summary.get('candidate_count', 0) if isinstance(summary, dict) else 0}",
        f"- groups: {format_counts(groups)}",
        "",
        "## Reviewer Instructions",
        "",
    ]
    instructions = packet.get("instructions", {})
    if isinstance(instructions, dict):
        lines.append(str(instructions.get("task", "")))
        lines.append("")
        for rule in instructions.get("rules", []):
            lines.append(f"- {rule}")
    lines.extend(
        [
            "",
            "## Candidates",
            "",
            "| group | request_id | route_id | target_model | reason | review_reasons | top_route | second_route | score | second_score | threshold | margin | match_source | match_index | prompt_review | duration_ms | upstream_status |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for candidate in packet.get("candidates", []):
        prompt_review = candidate.get("prompt_review") if isinstance(candidate, dict) else None
        prompt_review_label = ""
        if isinstance(prompt_review, dict):
            matched = "matched" if prompt_review.get("matched") is True else "unmatched"
            truncated = "truncated" if prompt_review.get("truncated") is True else "not_truncated"
            prompt_review_label = f"{matched},{truncated},chars={prompt_review.get('text_chars', '')}"
        lines.append(
            "| "
            + " | ".join(
                [
                    markdown_cell(candidate.get("group")),
                    markdown_cell(candidate.get("request_id")),
                    markdown_cell(candidate.get("route_id")),
                    markdown_cell(candidate.get("target_model")),
                    markdown_cell(candidate.get("reason")),
                    markdown_cell(",".join(candidate.get("review_reasons") or [])),
                    markdown_cell(candidate.get("top_route_id")),
                    markdown_cell(candidate.get("second_route_id")),
                    markdown_cell(candidate.get("score")),
                    markdown_cell(candidate.get("second_score")),
                    markdown_cell(candidate.get("threshold")),
                    markdown_cell(candidate.get("margin")),
                    markdown_cell(candidate.get("match_source")),
                    markdown_cell(candidate.get("match_index")),
                    markdown_cell(prompt_review_label),
                    markdown_cell(candidate.get("duration_ms")),
                    markdown_cell(candidate.get("upstream_status")),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Privacy Boundary",
            "",
            "Default packets are metadata-only. Prompt excerpts appear only when privacy_mode is raw_local.",
        ]
    )
    return "\n".join(lines) + "\n"


def format_counts(counts: Any) -> str:
    if not isinstance(counts, dict) or not counts:
        return "none"
    return ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))


def markdown_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|")


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare a local-only IntentMux AI review packet.")
    parser.add_argument("--input", required=True, help="JSON output from scripts/select_review_candidates.py")
    parser.add_argument("--prompt-path", action="append", default=[], help="Optional prompt review JSONL path or glob.")
    parser.add_argument("--include-prompt-text", choices=sorted(ALLOWED_PROMPT_TEXT_MODES), default="off")
    parser.add_argument("--max-prompt-chars", type=int, default=2000)
    parser.add_argument("--json-output", required=True)
    parser.add_argument("--markdown-output", required=True)
    args = parser.parse_args()

    candidate_report = load_json(Path(args.input))
    prompt_paths = expand_log_paths(args.prompt_path)
    prompt_records = load_prompt_review_records(prompt_paths) if prompt_paths else None
    packet = build_ai_review_packet(
        candidate_report,
        prompt_records=prompt_records,
        include_prompt_text=args.include_prompt_text,
        max_prompt_chars=args.max_prompt_chars,
    )

    json_output = Path(args.json_output)
    json_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    markdown_output = Path(args.markdown_output)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.write_text(render_markdown(packet), encoding="utf-8")


if __name__ == "__main__":
    main()
