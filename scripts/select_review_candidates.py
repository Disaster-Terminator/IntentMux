from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.router_log_summary import iter_lines, number_or_none, parse_route_records


REVIEW_REASON_PRIORITY = {
    "hard_rule": 110,
    "low_confidence": 100,
    "embedding_error": 90,
    "route_error": 85,
    "upstream_non_2xx": 80,
    "slow_request": 70,
    "near_threshold": 60,
    "near_margin": 50,
}

FALLBACK_THRESHOLD = 0.4
FALLBACK_MARGIN = 0.04


SAFE_CANDIDATE_FIELDS = {
    "event",
    "format_signals",
    "timestamp",
    "ts",
    "request_id",
    "route_id",
    "target_model",
    "reason",
    "score",
    "second_score",
    "score_margin",
    "threshold",
    "margin",
    "top_route_id",
    "second_route_id",
    "match_source",
    "match_index",
    "match_text_sha256",
    "match_score",
    "match_provenance",
    "duration_ms",
    "upstream_status",
    "outcome",
}


def select_review_candidates(
    records: Iterable[dict[str, Any]],
    *,
    threshold: float = FALLBACK_THRESHOLD,
    threshold_window: float = 0.03,
    margin: float = FALLBACK_MARGIN,
    margin_window: float = 0.02,
    slow_duration_ms: float = 60_000.0,
    limit: int = 50,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        review_reasons = review_reasons_for_record(
            record,
            threshold=threshold,
            threshold_window=threshold_window,
            margin=margin,
            margin_window=margin_window,
            slow_duration_ms=slow_duration_ms,
        )
        if not review_reasons:
            continue
        candidate = candidate_from_record(record)
        candidate["review_reasons"] = review_reasons
        candidate["_priority"] = max(REVIEW_REASON_PRIORITY[reason] for reason in review_reasons)
        candidate["_index"] = index
        candidates.append(candidate)

    candidates.sort(
        key=lambda candidate: (
            -candidate["_priority"],
            -float(candidate["duration_ms"] or 0.0),
            candidate["_index"],
        )
    )
    limited = candidates[: max(limit, 0)]
    for candidate in limited:
        candidate.pop("_priority", None)
        candidate.pop("_index", None)
    return limited


def prompt_review_index(
    records: Iterable[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for record in records:
        if record.get("event") != "prompt_review":
            continue
        request_id = record.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            continue
        latest_user_text = record.get("latest_user_text")
        text = latest_user_text if isinstance(latest_user_text, str) else ""
        indexed[request_id] = {
            "matched": True,
            "truncated": bool(record.get("truncated")),
            "text_chars": len(text),
        }
    return indexed


def attach_prompt_reviews(
    candidates: list[dict[str, Any]],
    prompt_records: Iterable[dict[str, Any]] | None,
) -> None:
    if prompt_records is None:
        return
    prompts_by_request_id = prompt_review_index(prompt_records)
    for candidate in candidates:
        request_id = candidate.get("request_id")
        if isinstance(request_id, str) and request_id in prompts_by_request_id:
            candidate["prompt_review"] = prompts_by_request_id[request_id]


def review_reasons_for_record(
    record: dict[str, Any],
    *,
    threshold: float,
    threshold_window: float,
    margin: float,
    margin_window: float,
    slow_duration_ms: float,
) -> list[str]:
    reasons: list[str] = []
    event = record.get("event")
    reason = record.get("reason")
    score = number_or_none(record.get("score"))
    second_score = number_or_none(record.get("second_score"))
    duration_ms = number_or_none(record.get("duration_ms"))

    if reason == "low_confidence":
        reasons.append("low_confidence")
    if reason == "embedding_error":
        reasons.append("embedding_error")
    if event == "route_error":
        reasons.append("route_error")
    if is_upstream_non_2xx(record.get("upstream_status")):
        reasons.append("upstream_non_2xx")
    if duration_ms is not None and duration_ms >= slow_duration_ms:
        reasons.append("slow_request")
    if isinstance(reason, str) and reason.startswith("hard_rule:"):
        reasons.append("hard_rule")
    if score is not None and abs(score - threshold) <= threshold_window:
        reasons.append("near_threshold")
    if score is not None and second_score is not None:
        score_margin = score - second_score
        if score_margin <= margin or abs(score_margin - margin) <= margin_window:
            reasons.append("near_margin")

    return reasons


def is_upstream_non_2xx(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value < 200 or value >= 300
    if isinstance(value, str) and value.isdigit():
        status = int(value)
        return status < 200 or status >= 300
    return False


def candidate_from_record(record: dict[str, Any]) -> dict[str, Any]:
    safe = {key: record.get(key) for key in SAFE_CANDIDATE_FIELDS if key in record}
    candidate = {
        "timestamp": safe.get("timestamp") or safe.get("ts"),
        "request_id": safe.get("request_id"),
        "route_id": safe.get("route_id"),
        "target_model": safe.get("target_model"),
        "reason": safe.get("reason"),
        "score": number_or_none(safe.get("score")),
        "second_score": number_or_none(safe.get("second_score")),
        "score_margin": number_or_none(safe.get("score_margin")),
        "threshold": number_or_none(safe.get("threshold")),
        "margin": number_or_none(safe.get("margin")),
        "top_route_id": safe.get("top_route_id"),
        "second_route_id": safe.get("second_route_id"),
        "match_source": safe.get("match_source"),
        "match_index": safe.get("match_index"),
        "match_text_sha256": safe.get("match_text_sha256"),
        "match_score": number_or_none(safe.get("match_score")),
        "match_provenance": safe.get("match_provenance"),
        "duration_ms": number_or_none(safe.get("duration_ms")),
        "upstream_status": safe.get("upstream_status"),
        "outcome": safe.get("outcome"),
        "event": safe.get("event"),
    }
    if isinstance(safe.get("format_signals"), dict):
        candidate["format_signals"] = safe["format_signals"]
    return candidate


def build_review_candidate_report(
    records: Iterable[dict[str, Any]],
    *,
    prompt_records: Iterable[dict[str, Any]] | None = None,
    log_paths: list[str] | None = None,
    prompt_log_paths: list[str] | None = None,
    threshold: float = FALLBACK_THRESHOLD,
    threshold_window: float = 0.03,
    margin: float = FALLBACK_MARGIN,
    margin_window: float = 0.02,
    slow_duration_ms: float = 60_000.0,
    limit: int = 50,
) -> dict[str, Any]:
    record_list = list(records)
    candidates = select_review_candidates(
        record_list,
        threshold=threshold,
        threshold_window=threshold_window,
        margin=margin,
        margin_window=margin_window,
        slow_duration_ms=slow_duration_ms,
        limit=limit,
    )
    attach_prompt_reviews(candidates, prompt_records)
    review_reasons = Counter(
        review_reason
        for candidate in candidates
        for review_reason in candidate.get("review_reasons", [])
    )
    hard_rules = Counter(
        str(candidate.get("reason", "")).split(":", 1)[1]
        for candidate in candidates
        if isinstance(candidate.get("reason"), str)
        and str(candidate["reason"]).startswith("hard_rule:")
        and ":" in str(candidate["reason"])
    )
    format_signal_counts = Counter(
        key
        for candidate in candidates
        if isinstance(candidate.get("format_signals"), dict)
        for key, value in candidate["format_signals"].items()
        if value is True
    )
    return {
        "summary": {
            "input_records": len(record_list),
            "candidate_count": len(candidates),
            "candidate_prompt_matches": sum(
                1
                for candidate in candidates
                if isinstance(candidate.get("prompt_review"), dict)
                and candidate["prompt_review"].get("matched") is True
            ),
            "format_signal_counts": dict(sorted(format_signal_counts.items())),
            "review_reasons": dict(sorted(review_reasons.items())),
            "routes": dict(sorted(Counter(candidate.get("route_id") for candidate in candidates if candidate.get("route_id")).items())),
            "targets": dict(sorted(Counter(candidate.get("target_model") for candidate in candidates if candidate.get("target_model")).items())),
            "hard_rules": dict(sorted(hard_rules.items())),
            "log_paths": log_paths or [],
            "prompt_log_paths": prompt_log_paths or [],
        },
        "candidates": candidates,
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    lines = [
        "# IntentMux Review Candidates",
        "",
        "## Summary",
        f"- input_records: {summary.get('input_records', 0)}",
        f"- candidate_count: {summary.get('candidate_count', 0)}",
        f"- candidate_prompt_matches: {summary.get('candidate_prompt_matches', 0)}",
        f"- format_signal_counts: {format_counts(summary.get('format_signal_counts', {}))}",
        f"- review_reasons: {format_counts(summary.get('review_reasons', {}))}",
        f"- routes: {format_counts(summary.get('routes', {}))}",
        f"- targets: {format_counts(summary.get('targets', {}))}",
        f"- hard_rules: {format_counts(summary.get('hard_rules', {}))}",
        "",
        "## Candidates",
        "",
        "| timestamp | request_id | route_id | target_model | reason | review_reasons | top_route | second_route | score | second_score | threshold | margin | match_source | match_index | match_text_sha256 | prompt_review | prompt_truncated | duration_ms | upstream_status |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for candidate in report.get("candidates", []):
        prompt_review = candidate.get("prompt_review")
        prompt_matched = ""
        prompt_truncated = ""
        if isinstance(prompt_review, dict) and prompt_review.get("matched") is True:
            prompt_matched = "matched"
            prompt_truncated = str(bool(prompt_review.get("truncated"))).lower()
        lines.append(
            "| "
            + " | ".join(
                [
                    markdown_cell(candidate.get("timestamp")),
                    markdown_cell(candidate.get("request_id")),
                    markdown_cell(candidate.get("route_id")),
                    markdown_cell(candidate.get("target_model")),
                    markdown_cell(candidate.get("reason")),
                    markdown_cell(",".join(candidate.get("review_reasons", []))),
                    markdown_cell(candidate.get("top_route_id")),
                    markdown_cell(candidate.get("second_route_id")),
                    markdown_cell(candidate.get("score")),
                    markdown_cell(candidate.get("second_score")),
                    markdown_cell(candidate.get("threshold")),
                    markdown_cell(candidate.get("margin")),
                    markdown_cell(candidate.get("match_source")),
                    markdown_cell(candidate.get("match_index")),
                    markdown_cell(candidate.get("match_text_sha256")),
                    markdown_cell(prompt_matched),
                    markdown_cell(prompt_truncated),
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
            "This report is derived from route audit metadata only. It must not contain raw prompts, completions, request bodies, tokens, or bearer credentials.",
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


def expand_log_paths(paths: list[str]) -> list[str]:
    expanded: list[str] = []
    for path in paths:
        matches = sorted(glob.glob(path))
        expanded.extend(matches or [path])
    return expanded


def load_route_thresholds(path: Path) -> tuple[float | None, float | None]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return None, None
    threshold = number_or_none(raw.get("threshold"))
    margin = number_or_none(raw.get("margin"))
    return threshold, margin


def load_prompt_review_records(paths: list[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in iter_lines(paths):
        line = line.strip()
        if not line or "{" not in line:
            continue
        json_start = line.find("{")
        try:
            record = json.loads(line[json_start:])
        except json.JSONDecodeError:
            continue
        if record.get("event") == "prompt_review":
            records.append(record)
    return records


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Select metadata-only IntentMux route log records for human review.",
    )
    parser.add_argument("paths", nargs="*", help="Route audit JSONL files or globs. Reads stdin when omitted.")
    parser.add_argument(
        "--routes",
        default=str(REPO_ROOT / "config/routes.yaml"),
        help="Routes YAML to read default threshold and margin from.",
    )
    parser.add_argument("--threshold", type=float)
    parser.add_argument("--threshold-window", type=float, default=0.03)
    parser.add_argument("--margin", type=float, default=0.04)
    parser.add_argument("--margin-window", type=float, default=0.02)
    parser.add_argument("--slow-duration-ms", type=float, default=60_000.0)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument(
        "--prompt-path",
        action="append",
        default=[],
        help="Optional prompt review JSONL file or glob. Joined by request_id; raw text is never emitted.",
    )
    parser.add_argument("--json-output")
    parser.add_argument("--markdown-output")
    args = parser.parse_args()

    route_threshold = route_margin = None
    if args.routes:
        route_threshold, route_margin = load_route_thresholds(Path(args.routes))
    threshold = args.threshold if args.threshold is not None else route_threshold
    margin = args.margin if args.margin is not None else route_margin

    log_paths = expand_log_paths(args.paths)
    prompt_log_paths = expand_log_paths(args.prompt_path)
    records = list(parse_route_records(iter_lines(log_paths)))
    prompt_records = load_prompt_review_records(prompt_log_paths) if prompt_log_paths else None
    report = build_review_candidate_report(
        records,
        prompt_records=prompt_records,
        log_paths=log_paths,
        prompt_log_paths=prompt_log_paths,
        threshold=FALLBACK_THRESHOLD if threshold is None else threshold,
        threshold_window=args.threshold_window,
        margin=FALLBACK_MARGIN if margin is None else margin,
        margin_window=args.margin_window,
        slow_duration_ms=args.slow_duration_ms,
        limit=args.limit,
    )

    if args.json_output:
        json_path = Path(args.json_output)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.markdown_output:
        markdown_path = Path(args.markdown_output)
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_markdown(report), encoding="utf-8")
    if not args.json_output and not args.markdown_output:
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()
