from __future__ import annotations

import argparse
import glob
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
import re
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

AGENT_PROMPT_MARKERS = (
    "coding agent",
    "read-only audit",
    "readonly audit",
    "do not edit files",
    "do not modify files",
    "provide concrete recommendations",
    "inspect the current diff",
    "inspect the relevant",
    "inspect the repo",
    "inspect the repository",
    "use tools",
    "只读审查",
    "只读调查",
    "不要编辑文件",
    "不要修改文件",
    "不要改文件",
    "提供具体建议",
    "检查当前 diff",
    "审查当前 diff",
)
SYSTEM_BOILERPLATE_MARKERS = (
    "[important:",
    "has invoked the",
    "skill]",
    "system-reminder",
    "extremely_important",
    "agents.md",
    "instruction priority",
    "you are chatgpt",
)
CJK_RE = re.compile(r"[\u3400-\u9fff]")
LATIN_RE = re.compile(r"[A-Za-z]")


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
    *,
    classify_prompts: bool = False,
    agent_prompt_hashes: set[str] | None = None,
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
        prompt_review = {
            "matched": True,
            "truncated": bool(record.get("truncated")),
            "text_chars": len(text),
        }
        if classify_prompts:
            prompt_review.update(
                classify_prompt_review_text(text, agent_prompt_hashes=agent_prompt_hashes),
            )
        indexed[request_id] = prompt_review
    return indexed


def attach_prompt_reviews(
    candidates: list[dict[str, Any]],
    prompt_records: Iterable[dict[str, Any]] | None,
    *,
    classify_prompts: bool = False,
    agent_prompt_hashes: set[str] | None = None,
) -> None:
    if prompt_records is None:
        return
    prompts_by_request_id = prompt_review_index(
        prompt_records,
        classify_prompts=classify_prompts,
        agent_prompt_hashes=agent_prompt_hashes,
    )
    for candidate in candidates:
        request_id = candidate.get("request_id")
        if isinstance(request_id, str) and request_id in prompts_by_request_id:
            candidate["prompt_review"] = prompts_by_request_id[request_id]


def classify_prompt_review_text(
    text: str,
    *,
    agent_prompt_hashes: set[str] | None = None,
) -> dict[str, str]:
    lowered = text.lower()
    cjk_count = len(CJK_RE.findall(text))
    latin_count = len(LATIN_RE.findall(text))
    visible_count = max(sum(not char.isspace() for char in text), 1)
    cjk_ratio = cjk_count / visible_count
    text_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()

    if agent_prompt_hashes and text_sha256 in agent_prompt_hashes:
        prompt_kind = "agent_generated"
        value_tier = "baseline"
        prompt_origin = "retinue_job_prompt"
    elif any(marker in lowered for marker in SYSTEM_BOILERPLATE_MARKERS):
        prompt_kind = "system_boilerplate"
        value_tier = "ignore"
        prompt_origin = "system_boilerplate"
    elif any(marker in lowered for marker in AGENT_PROMPT_MARKERS):
        prompt_kind = "agent_generated"
        value_tier = "baseline"
        prompt_origin = "agent_prompt_pattern"
    elif cjk_count >= 4 and cjk_ratio >= 0.35:
        prompt_kind = "manual_zh"
        value_tier = "high"
        prompt_origin = "local_prompt_log"
    elif cjk_count >= 4 and latin_count >= 20:
        prompt_kind = "mixed"
        value_tier = "baseline"
        prompt_origin = "local_prompt_log"
    else:
        prompt_kind = "unknown"
        value_tier = "baseline"
        prompt_origin = "local_prompt_log"

    if cjk_count >= 4 and cjk_ratio >= 0.25:
        language = "zh-CN"
    elif latin_count >= 4:
        language = "en"
    else:
        language = "unknown"

    return {
        "prompt_language": language,
        "prompt_kind": prompt_kind,
        "prompt_value_tier": value_tier,
        "prompt_origin": prompt_origin,
    }


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
    classify_prompts: bool = False,
    prompt_language_filter: str | None = None,
    prompt_kind_filter: str | None = None,
    prompt_origin_filter: str | None = None,
    min_prompt_chars: int | None = None,
    max_prompt_chars: int | None = None,
    agent_prompt_hashes: set[str] | None = None,
) -> dict[str, Any]:
    record_list = list(records)
    prompt_filters_enabled = any(
        value is not None
        for value in (
            prompt_language_filter,
            prompt_kind_filter,
            prompt_origin_filter,
            min_prompt_chars,
            max_prompt_chars,
        )
    )
    candidates = select_review_candidates(
        record_list,
        threshold=threshold,
        threshold_window=threshold_window,
        margin=margin,
        margin_window=margin_window,
        slow_duration_ms=slow_duration_ms,
        limit=max(len(record_list), limit) if prompt_filters_enabled else limit,
    )
    attach_prompt_reviews(
        candidates,
        prompt_records,
        classify_prompts=classify_prompts or prompt_filters_enabled,
        agent_prompt_hashes=agent_prompt_hashes,
    )
    if prompt_filters_enabled:
        candidates = [
            candidate
            for candidate in candidates
            if prompt_review_matches_filters(
                candidate.get("prompt_review"),
                prompt_language_filter=prompt_language_filter,
                prompt_kind_filter=prompt_kind_filter,
                prompt_origin_filter=prompt_origin_filter,
                min_prompt_chars=min_prompt_chars,
                max_prompt_chars=max_prompt_chars,
            )
        ]
    if classify_prompts or prompt_filters_enabled:
        candidates.sort(key=prompt_value_sort_key)
    candidates = candidates[: max(limit, 0)]
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
    prompt_value_tiers = Counter(
        prompt_review.get("prompt_value_tier")
        for candidate in candidates
        if isinstance((prompt_review := candidate.get("prompt_review")), dict)
        and prompt_review.get("prompt_value_tier")
    )
    prompt_origins = Counter(
        prompt_review.get("prompt_origin")
        for candidate in candidates
        if isinstance((prompt_review := candidate.get("prompt_review")), dict)
        and prompt_review.get("prompt_origin")
    )
    summary = {
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
        "routes": dict(
            sorted(
                Counter(
                    candidate.get("route_id")
                    for candidate in candidates
                    if candidate.get("route_id")
                ).items()
            )
        ),
        "targets": dict(
            sorted(
                Counter(
                    candidate.get("target_model")
                    for candidate in candidates
                    if candidate.get("target_model")
                ).items()
            )
        ),
        "hard_rules": dict(sorted(hard_rules.items())),
        "log_paths": log_paths or [],
        "prompt_log_paths": prompt_log_paths or [],
    }
    if prompt_value_tiers:
        summary["prompt_value_tiers"] = dict(sorted(prompt_value_tiers.items()))
    if prompt_origins:
        summary["prompt_origins"] = dict(sorted(prompt_origins.items()))
    return {
        "summary": summary,
        "candidates": candidates,
    }


def prompt_review_matches_filters(
    prompt_review: Any,
    *,
    prompt_language_filter: str | None,
    prompt_kind_filter: str | None,
    prompt_origin_filter: str | None,
    min_prompt_chars: int | None,
    max_prompt_chars: int | None,
) -> bool:
    if not isinstance(prompt_review, dict) or prompt_review.get("matched") is not True:
        return False
    if (
        prompt_language_filter is not None
        and prompt_review.get("prompt_language") != prompt_language_filter
    ):
        return False
    if prompt_kind_filter is not None and prompt_review.get("prompt_kind") != prompt_kind_filter:
        return False
    if (
        prompt_origin_filter is not None
        and prompt_review.get("prompt_origin") != prompt_origin_filter
    ):
        return False
    text_chars = number_or_none(prompt_review.get("text_chars"))
    if min_prompt_chars is not None and (text_chars is None or text_chars < min_prompt_chars):
        return False
    if max_prompt_chars is not None and (text_chars is None or text_chars > max_prompt_chars):
        return False
    return True


def prompt_value_sort_key(candidate: dict[str, Any]) -> tuple[int, float]:
    prompt_review = candidate.get("prompt_review")
    tier = prompt_review.get("prompt_value_tier") if isinstance(prompt_review, dict) else None
    tier_rank = {"high": 0, "baseline": 1, "ignore": 2}.get(str(tier), 3)
    return (tier_rank, -float(candidate.get("duration_ms") or 0.0))


def render_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    lines = [
        "# IntentMux Review Candidates",
        "",
        "## Summary",
        f"- input_records: {summary.get('input_records', 0)}",
        f"- candidate_count: {summary.get('candidate_count', 0)}",
        f"- candidate_prompt_matches: {summary.get('candidate_prompt_matches', 0)}",
        f"- prompt_value_tiers: {format_counts(summary.get('prompt_value_tiers', {}))}",
        f"- prompt_origins: {format_counts(summary.get('prompt_origins', {}))}",
        f"- format_signal_counts: {format_counts(summary.get('format_signal_counts', {}))}",
        f"- review_reasons: {format_counts(summary.get('review_reasons', {}))}",
        f"- routes: {format_counts(summary.get('routes', {}))}",
        f"- targets: {format_counts(summary.get('targets', {}))}",
        f"- hard_rules: {format_counts(summary.get('hard_rules', {}))}",
        "",
        "## Candidates",
        "",
        "| timestamp | request_id | route_id | target_model | reason | review_reasons | top_route | second_route | score | second_score | threshold | margin | match_source | match_index | match_text_sha256 | prompt_review | prompt_kind | prompt_value | prompt_origin | prompt_truncated | duration_ms | upstream_status |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for candidate in report.get("candidates", []):
        prompt_review = candidate.get("prompt_review")
        prompt_matched = ""
        prompt_kind = ""
        prompt_value = ""
        prompt_origin = ""
        prompt_truncated = ""
        if isinstance(prompt_review, dict) and prompt_review.get("matched") is True:
            prompt_matched = "matched"
            prompt_kind = str(prompt_review.get("prompt_kind") or "")
            prompt_value = str(prompt_review.get("prompt_value_tier") or "")
            prompt_origin = str(prompt_review.get("prompt_origin") or "")
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
                    markdown_cell(prompt_kind),
                    markdown_cell(prompt_value),
                    markdown_cell(prompt_origin),
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


def load_agent_prompt_hashes(paths: list[str]) -> set[str]:
    hashes: set[str] = set()
    for path in paths:
        file_path = Path(path)
        if not file_path.is_file():
            continue
        if file_path.name == "meta.json":
            try:
                raw = json.loads(file_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            prompt_sha256 = raw.get("promptSha256")
            if isinstance(prompt_sha256, str) and len(prompt_sha256) == 64:
                hashes.add(prompt_sha256.lower())
            continue
        try:
            text = file_path.read_text(encoding="utf-8")
        except OSError:
            continue
        hashes.add(hashlib.sha256(text.encode("utf-8")).hexdigest())
    return hashes


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
        "--classify-prompts",
        action="store_true",
        help="Attach safe prompt language/kind/value metadata from local prompt review logs.",
    )
    parser.add_argument(
        "--prompt-language-filter",
        "--lang-filter",
        dest="prompt_language_filter",
        help="Keep only candidates whose prompt_review prompt_language matches this value.",
    )
    parser.add_argument(
        "--prompt-kind-filter",
        "--kind-filter",
        dest="prompt_kind_filter",
        help="Keep only candidates whose prompt_review prompt_kind matches this value.",
    )
    parser.add_argument(
        "--prompt-origin-filter",
        "--origin-filter",
        dest="prompt_origin_filter",
        help="Keep only candidates whose prompt_review prompt_origin matches this value.",
    )
    parser.add_argument("--min-prompt-chars", type=int)
    parser.add_argument("--max-prompt-chars", type=int)
    parser.add_argument(
        "--prompt-path",
        action="append",
        default=[],
        help="Optional prompt review JSONL file or glob. Joined by request_id; raw text is never emitted.",
    )
    parser.add_argument(
        "--agent-prompt-path",
        "--retinue-prompt-path",
        action="append",
        default=[],
        dest="agent_prompt_path",
        help=(
            "Optional local agent prompt files or meta.json globs. Their SHA256 values mark "
            "exact prompt matches as agent_generated without emitting raw text."
        ),
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
    agent_prompt_paths = expand_log_paths(args.agent_prompt_path)
    records = list(parse_route_records(iter_lines(log_paths)))
    prompt_records = load_prompt_review_records(prompt_log_paths) if prompt_log_paths else None
    agent_prompt_hashes = load_agent_prompt_hashes(agent_prompt_paths) if agent_prompt_paths else None
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
        classify_prompts=args.classify_prompts,
        prompt_language_filter=args.prompt_language_filter,
        prompt_kind_filter=args.prompt_kind_filter,
        prompt_origin_filter=args.prompt_origin_filter,
        min_prompt_chars=args.min_prompt_chars,
        max_prompt_chars=args.max_prompt_chars,
        agent_prompt_hashes=agent_prompt_hashes,
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
