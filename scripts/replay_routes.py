#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import ipaddress
import json
from pathlib import Path
import sys
from typing import Any, Iterable
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from router.config import load_settings
from router.embedding import OpenAIEmbeddingClient
from router.routing import Router, sha256_text
from scripts.eval_routes import (
    BASELINES,
    MockEmbeddingClient,
    decide_for_baseline,
    router_for_baseline,
)
from scripts.select_review_candidates import expand_log_paths


DEFAULT_BASELINES = ("current-router", "always-lite", "always-deep", "hard-rule-only")


def iter_jsonl(paths: list[str]) -> Iterable[dict[str, Any]]:
    for path in paths:
        with Path(path).open(encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    payload = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    yield payload


def replay_case_from_record(record: dict[str, Any], index: int) -> dict[str, Any] | None:
    text = record.get("latest_user_text") or record.get("text") or record.get("prompt")
    if not isinstance(text, str) or not text.strip():
        return None
    request_id = record.get("request_id")
    case_id = request_id if isinstance(request_id, str) and request_id else f"case_{index:04d}"
    label = record.get("expect") or record.get("expected_route")
    label_source = "explicit_label" if isinstance(label, str) else None
    if not isinstance(label, str):
        label = record.get("route_id")
        label_source = "historical_route_id" if isinstance(label, str) else None
    return {
        "id": case_id,
        "request_id": request_id if isinstance(request_id, str) else None,
        "text": text,
        "reference_route": label if isinstance(label, str) else None,
        "reference_route_source": label_source,
        "source_event": record.get("event"),
        "historical_reason": record.get("reason"),
        "historical_target_model": record.get("target_model"),
        "truncated": bool(record.get("truncated")),
    }


def load_replay_cases(paths: list[str], *, limit: int | None = None) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for index, record in enumerate(iter_jsonl(paths), start=1):
        case = replay_case_from_record(record, index)
        if case is None:
            continue
        cases.append(case)
        if limit is not None and len(cases) >= limit:
            break
    return cases


async def replay_routes(
    *,
    input_paths: list[str],
    routes_path: Path,
    baselines: list[str],
    mock_embeddings: bool = False,
    allow_remote_embeddings: bool = False,
    limit: int | None = None,
    include_text: bool = False,
) -> dict[str, Any]:
    unknown = sorted(set(baselines) - BASELINES)
    if unknown:
        raise ValueError(f"unsupported baseline(s): {', '.join(unknown)}")

    settings = load_settings(routes_path)
    if not mock_embeddings and not allow_remote_embeddings:
        validate_local_embedding_url(settings.embedding_url)
    embedding_client = (
        MockEmbeddingClient.from_settings(settings)
        if mock_embeddings
        else OpenAIEmbeddingClient(
            settings.embedding_url,
            settings.embedding_model,
            api_key=settings.embedding_api_key,
            headers=settings.embedding_headers,
        )
    )
    router = Router(settings, embedding_client)
    cases = load_replay_cases(input_paths, limit=limit)
    rows: list[dict[str, Any]] = []
    baseline_counts: dict[str, Counter[str]] = {baseline: Counter() for baseline in baselines}
    baseline_agreement: Counter[str] = Counter()
    baseline_agreement_by_source: dict[str, Counter[str]] = {
        baseline: Counter() for baseline in baselines
    }
    reference_counts: Counter[str] = Counter()
    reference_source_counts: Counter[str] = Counter()

    for case in cases:
        request_json = {
            "model": settings.route_model,
            "messages": [{"role": "user", "content": case["text"]}],
        }
        reference_route = case.get("reference_route")
        reference_source = case.get("reference_route_source")
        if isinstance(reference_route, str):
            reference_counts[reference_route] += 1
        if isinstance(reference_source, str):
            reference_source_counts[reference_source] += 1
        decisions: dict[str, dict[str, Any]] = {}
        for baseline in baselines:
            decision_router = router_for_baseline(router, baseline)
            decision = await decide_for_baseline(decision_router, request_json, baseline)
            actual_route = decision.route_id or decision.target_model
            baseline_counts[baseline][str(actual_route)] += 1
            if reference_route and actual_route == reference_route:
                baseline_agreement[baseline] += 1
                if isinstance(reference_source, str):
                    baseline_agreement_by_source[baseline][reference_source] += 1
            decisions[baseline] = {
                "route_id": actual_route,
                "target_model": decision.target_model,
                "reason": decision.reason,
                "score": decision.score,
                "second_score": decision.second_score,
                "score_margin": decision.score_margin,
                "threshold": decision.threshold,
                "margin": decision.margin,
                "top_route_id": decision.top_route_id,
                "second_route_id": decision.second_route_id,
                "match_source": decision.match_source,
                "match_index": decision.match_index,
                "match_text_sha256": decision.match_text_sha256,
                "match_score": decision.match_score,
                "match_provenance": decision.match_provenance,
            }
        row = {
            "id": case["id"],
            "request_id": case.get("request_id"),
            "text_sha256": sha256_text(case["text"]),
            "text_chars": len(case["text"]),
            "reference_route": reference_route,
            "reference_route_source": case.get("reference_route_source"),
            "source_event": case.get("source_event"),
            "historical_reason": case.get("historical_reason"),
            "historical_target_model": case.get("historical_target_model"),
            "truncated": case.get("truncated"),
            "decisions": decisions,
        }
        if include_text:
            row["text"] = case["text"]
        rows.append(row)

    return {
        "schema": "intentmux-route-replay-v1",
        "routes_path": str(routes_path),
        "input_paths": input_paths,
        "baselines": baselines,
        "summary": {
            "case_count": len(rows),
            "reference_routes": dict(sorted(reference_counts.items())),
            "reference_route_sources": dict(sorted(reference_source_counts.items())),
            "baseline_routes": {
                baseline: dict(sorted(counts.items()))
                for baseline, counts in baseline_counts.items()
            },
            "baseline_reference_agreement": {
                baseline: baseline_agreement.get(baseline, 0) for baseline in baselines
            },
            "baseline_reference_agreement_by_source": {
                baseline: dict(sorted(counts.items()))
                for baseline, counts in baseline_agreement_by_source.items()
            },
            "raw_text_included": include_text,
            "remote_embeddings_allowed": allow_remote_embeddings,
        },
        "cases": rows,
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    lines = [
        "# IntentMux Route Replay",
        "",
        "## Summary",
        f"- case_count: {summary.get('case_count', 0)}",
        f"- reference_routes: {format_counts(summary.get('reference_routes', {}))}",
        f"- reference_route_sources: {format_counts(summary.get('reference_route_sources', {}))}",
        f"- raw_text_included: {str(summary.get('raw_text_included', False)).lower()}",
        f"- remote_embeddings_allowed: {str(summary.get('remote_embeddings_allowed', False)).lower()}",
        "",
        "## Baselines",
        "",
        "| baseline | routes | reference_agreement |",
        "| --- | --- | ---: |",
    ]
    baseline_routes = summary.get("baseline_routes", {})
    agreements = summary.get("baseline_reference_agreement", {})
    agreements_by_source = summary.get("baseline_reference_agreement_by_source", {})
    if isinstance(baseline_routes, dict):
        for baseline, routes in sorted(baseline_routes.items()):
            source_counts = {}
            if isinstance(agreements_by_source, dict) and isinstance(
                agreements_by_source.get(baseline), dict
            ):
                source_counts = agreements_by_source[baseline]
            lines.append(
                f"| {baseline} | {format_counts(routes)} | "
                f"{agreements.get(baseline, 0)} ({format_counts(source_counts)}) |"
            )
    lines.extend(
        [
            "",
            "## Cases",
            "",
        "| id | reference | reference_source | current | current_reason | top_route | second_route | current_score | threshold | margin | match_source | match_index | match_text_sha256 | text_sha256 | text_chars |",
            "| --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | --- | ---: | --- | --- | ---: |",
        ]
    )
    for case in report.get("cases", []):
        if not isinstance(case, dict):
            continue
        current = {}
        decisions = case.get("decisions")
        if isinstance(decisions, dict) and isinstance(decisions.get("current-router"), dict):
            current = decisions["current-router"]
        lines.append(
            "| "
            + " | ".join(
                [
                    markdown_cell(case.get("id")),
                    markdown_cell(case.get("reference_route")),
                    markdown_cell(case.get("reference_route_source")),
                    markdown_cell(current.get("route_id")),
                    markdown_cell(current.get("reason")),
                    markdown_cell(current.get("top_route_id")),
                    markdown_cell(current.get("second_route_id")),
                    markdown_cell(current.get("score")),
                    markdown_cell(current.get("threshold")),
                    markdown_cell(current.get("margin")),
                    markdown_cell(current.get("match_source")),
                    markdown_cell(current.get("match_index")),
                    markdown_cell(current.get("match_text_sha256")),
                    markdown_cell(case.get("text_sha256")),
                    markdown_cell(case.get("text_chars")),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "Replay is an offline routing reproducibility check. Historical route_id is drift evidence, not ground truth unless the input was explicitly labeled.",
        ]
    )
    return "\n".join(lines) + "\n"


def format_counts(counts: Any) -> str:
    if not isinstance(counts, dict) or not counts:
        return "none"
    return ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))


def compact_stdout_summary(report: dict[str, Any]) -> dict[str, Any]:
    summary = report["summary"]
    return {
        "schema": "intentmux-route-replay-summary-v1",
        "case_count": summary["case_count"],
        "raw_text_included": summary["raw_text_included"],
        "remote_embeddings_allowed": summary["remote_embeddings_allowed"],
        "reference_routes": summary["reference_routes"],
        "reference_route_sources": summary["reference_route_sources"],
        "baseline_routes": summary["baseline_routes"],
        "baseline_reference_agreement": summary["baseline_reference_agreement"],
        "note": "Full replay cases are written only with --json-output or --markdown-output.",
    }


def markdown_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|")


def validate_local_embedding_url(url: str) -> None:
    parsed = urlparse(url)
    hostname = parsed.hostname
    if hostname is None:
        raise ValueError("embedding_url must include a hostname")
    if is_local_or_private_host(hostname):
        return
    raise ValueError(
        "replay would send prompt text to a non-local embedding endpoint; "
        "use --allow-remote-embeddings only for trusted private review runs"
    )


def is_local_or_private_host(hostname: str) -> bool:
    lowered = hostname.lower()
    if lowered in {"localhost", "host.docker.internal"}:
        return True
    try:
        address = ipaddress.ip_address(lowered)
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_link_local


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay local prompt-review samples through current and baseline routers.",
    )
    parser.add_argument("paths", nargs="+", help="Replay JSONL or prompt_review JSONL files/globs.")
    parser.add_argument("--routes", default=str(REPO_ROOT / "config/routes.yaml"))
    parser.add_argument(
        "--baseline",
        action="append",
        choices=sorted(BASELINES),
        help="Baseline to run. Repeatable. Defaults to current-router, always-lite, always-deep, hard-rule-only.",
    )
    parser.add_argument("--mock-embeddings", action="store_true")
    parser.add_argument(
        "--allow-remote-embeddings",
        action="store_true",
        help="Allow replay to send prompt text to a non-local embedding endpoint.",
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--include-text", action="store_true")
    parser.add_argument("--json-output")
    parser.add_argument("--markdown-output")
    args = parser.parse_args()

    if args.include_text and not (args.json_output or args.markdown_output):
        parser.error("--include-text requires --json-output or --markdown-output")

    input_paths = expand_log_paths(args.paths)
    report = asyncio.run(
        replay_routes(
            input_paths=input_paths,
            routes_path=Path(args.routes),
            baselines=args.baseline or list(DEFAULT_BASELINES),
            mock_embeddings=args.mock_embeddings,
            allow_remote_embeddings=args.allow_remote_embeddings,
            limit=args.limit,
            include_text=args.include_text,
        )
    )
    if args.json_output:
        output = Path(args.json_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.markdown_output:
        output = Path(args.markdown_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(render_markdown(report), encoding="utf-8")
    if not args.json_output and not args.markdown_output:
        print(json.dumps(compact_stdout_summary(report), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
