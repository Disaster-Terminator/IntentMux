#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from router.observability import DEFAULT_AUDIT_LOG_TIMEZONE, zoneinfo_for

try:
    from scripts.router_log_summary import parse_route_records
except ModuleNotFoundError:
    from router_log_summary import parse_route_records

DEFAULT_REPO = Path(__file__).resolve().parents[1]
DEFAULT_LOG_DIR = Path(os.getenv("INTENTMUX_LOG_DIR", "logs"))
DEFAULT_ROUTER_BASE_URL = os.getenv("INTENTMUX_ROUTER_BASE_URL", "http://127.0.0.1:4001")
DEFAULT_LITELLM_BASE_URL = os.getenv("INTENTMUX_LITELLM_BASE_URL", "http://127.0.0.1:4000")
DEFAULT_TIMEZONE = os.getenv("INTENTMUX_TIMEZONE", DEFAULT_AUDIT_LOG_TIMEZONE)


def run(cmd: str, *, cwd: Path, timeout: int = 120) -> dict[str, Any]:
    proc = subprocess.run(
        ["bash", "-lc", cmd],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "stdout": (proc.stdout or "").strip(),
        "stderr": (proc.stderr or "").strip(),
        "cmd": cmd,
    }


def http_get_json(url: str, timeout: int = 5) -> tuple[int | None, dict[str, Any] | None, str | None]:
    try:
        req = Request(url, headers={"User-Agent": "intentmux-daily-health"})
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(body), None
    except HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return exc.code, None, f"HTTP {exc.code}: {body[:180]}"
    except Exception as exc:
        return None, None, str(exc)


def keep(
    lines: str,
    keywords: list[str],
    *,
    max_lines: int = 40,
    default_truncate: int = 220,
    no_truncate_keywords: tuple[str, ...] = (
        "reasons:",
        "upstream_non_200",
        "slow_requests",
        "duration_ms=",
    ),
) -> list[str]:
    out: list[str] = []
    for ln in lines.splitlines():
        lo = ln.lower()
        if not any(k in lo for k in keywords):
            continue
        if any(k in lo for k in no_truncate_keywords):
            out.append(ln)
        else:
            out.append(ln[:default_truncate])
    return out[-max_lines:]


def parse_ready(payload: dict[str, Any] | None, code: int | None, err: str | None) -> tuple[bool, str, dict[str, Any]]:
    if not payload:
        return False, f"http={code} err={err}", {"http": code, "error": err}

    # 新契约：components.{router,litellm,embedding}
    components = payload.get("components") if isinstance(payload.get("components"), dict) else {}
    router_ok = (components.get("router") or {}).get("ok")
    embedding_ok = (components.get("embedding") or {}).get("ok")
    litellm = components.get("litellm") or {}
    litellm_ok = litellm.get("ok")
    litellm_detail = litellm.get("detail")

    summary = (
        f"ready={payload.get('ready')} "
        f"router={router_ok} "
        f"embedding={embedding_ok} "
        f"litellm_ok={litellm_ok} "
        f"litellm_detail={litellm_detail}"
    )
    ok = bool(payload.get("ready") is True)
    return ok, summary, {
        "http": code,
        "ready": payload.get("ready"),
        "router_ok": router_ok,
        "embedding_ok": embedding_ok,
        "litellm_ok": litellm_ok,
        "litellm_detail": litellm_detail,
        "error": err,
    }


def budget_no_samples(day_log: Path) -> bool:
    return (not day_log.exists()) or day_log.stat().st_size == 0


def count_route_records(day_log: Path) -> int:
    if not day_log.exists():
        return 0
    with day_log.open("r", encoding="utf-8") as fh:
        return sum(1 for _ in parse_route_records(fh))


def traffic_evidence_from_day_log(day_log: Path, *, min_records: int) -> dict[str, Any]:
    today_records = count_route_records(day_log)
    if min_records <= 0:
        return {
            "ok": True,
            "today_records": today_records,
            "min_records": min_records,
            "detail": "not_required",
        }
    if today_records >= min_records:
        detail = f"sufficient_samples: today_records={today_records} min_records={min_records}"
        return {
            "ok": True,
            "today_records": today_records,
            "min_records": min_records,
            "detail": detail,
        }
    detail = f"insufficient_samples: today_records={today_records} min_records={min_records}"
    return {
        "ok": False,
        "today_records": today_records,
        "min_records": min_records,
        "detail": detail,
    }


def report_now_and_day(
    *,
    now: datetime | None = None,
    timezone_name: str = DEFAULT_TIMEZONE,
    explicit_date: str | None = None,
) -> tuple[datetime, str]:
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    localized = current.astimezone(zoneinfo_for(timezone_name))
    return localized, explicit_date or localized.strftime("%Y-%m-%d")


def path_from_arg_or_env(value: str | None, env_name: str, default: Path) -> Path:
    raw = value or os.getenv(env_name)
    return Path(raw).expanduser() if raw else default


def build_e2e_cmd(
    *,
    litellm_base_url: str,
    log_container: str,
    litellm_env: Path | None,
) -> str:
    parts: list[str] = []
    if litellm_env is not None:
        parts.append(f"set -a; . {shlex.quote(str(litellm_env))}; set +a;")
    parts.append(
        "uv run python scripts/e2e_litellm_entry.py "
        f"--litellm-base-url {shlex.quote(litellm_base_url)} "
        f"--log-container {shlex.quote(log_container)} "
        "--log-tail 300 --require-request-id-log-match"
    )
    return " ".join(parts)


def render_md(report: dict[str, Any]) -> str:
    r = report
    lines = [
        "# IntentMux Daily Health",
        "",
        f"time: {r['time']}",
        f"repo: {r['repo']}",
        f"commit: {r['commit']}",
        "",
        "## ready",
        f"- ok: {r['ready']['ok']}",
        f"- summary: {r['ready']['summary']}",
        "",
        "## route_summary_today",
        f"- exit_code: {r['route_summary_today']['exit_code']}",
    ]
    for ln in r["route_summary_today"].get("highlights", []):
        append_md_highlight(lines, ln)

    lines += [
        "",
        "## route_summary_all_logs",
        f"- exit_code: {r['route_summary_all_logs']['exit_code']}",
    ]
    for ln in r["route_summary_all_logs"].get("highlights", []):
        append_md_highlight(lines, ln)

    traffic = r.get("traffic_evidence")
    if traffic:
        lines += [
            "",
            "## traffic_evidence",
            f"- ok: {traffic['ok']}",
            f"- today_records: {traffic['today_records']}",
            f"- min_records: {traffic['min_records']}",
            f"- detail: {traffic['detail']}",
        ]

    lines += [
        "",
        "## strict_budget",
        f"- exit_code: {r['strict_budget']['exit_code']}",
    ]
    for ln in r["strict_budget"].get("reasons", []):
        append_md_highlight(lines, ln)

    lines += [
        "",
        "## tolerant_budget",
        f"- exit_code: {r['tolerant_budget']['exit_code']}",
    ]
    for ln in r["tolerant_budget"].get("reasons", []):
        append_md_highlight(lines, ln)

    lines += [
        "",
        "## e2e",
        f"- mode: {r['e2e']['mode']}",
        f"- exit_code: {r['e2e']['exit_code']}",
    ]
    for ln in r["e2e"].get("highlights", []):
        append_md_highlight(lines, ln)

    lines += [
        "",
        "## paths",
        f"- json: {r['paths']['json']}",
        f"- md: {r['paths']['md']}",
        "",
    ]
    return "\n".join(lines)


def append_md_highlight(lines: list[str], line: str) -> None:
    if line.startswith("- "):
        lines.append(f"  {line}")
    else:
        lines.append(f"- {line}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-e2e", action="store_true", help="Run strict LiteLLM-entry e2e (real requests)")
    ap.add_argument("--slow-request-limit", type=int, default=10)
    ap.add_argument(
        "--timezone",
        default=DEFAULT_TIMEZONE,
        help=(
            "Timezone used for report timestamps and today's route-log filename. "
            "Defaults to INTENTMUX_TIMEZONE or Asia/Shanghai."
        ),
    )
    ap.add_argument(
        "--date",
        help="Explicit route-log date in YYYY-MM-DD. Overrides --timezone for file selection.",
    )
    ap.add_argument(
        "--min-route-records",
        type=int,
        default=int(os.getenv("INTENTMUX_MIN_ROUTE_RECORDS", "0")),
        help=(
            "Minimum non-empty records required in today's route log before the "
            "report can claim traffic evidence. Defaults to INTENTMUX_MIN_ROUTE_RECORDS or 0."
        ),
    )
    ap.add_argument(
        "--repo",
        help="IntentMux repository path. Defaults to this script's repository, or INTENTMUX_REPO.",
    )
    ap.add_argument(
        "--log-dir",
        help="Directory containing routes/ and health/. Defaults to logs, or INTENTMUX_LOG_DIR.",
    )
    ap.add_argument(
        "--route-log-glob",
        help="Glob for all route audit logs. Defaults to <log-dir>/routes/*.jsonl, or INTENTMUX_ROUTE_LOG_GLOB.",
    )
    ap.add_argument(
        "--router-base-url",
        default=DEFAULT_ROUTER_BASE_URL,
        help="IntentMux base URL for /ready. Defaults to INTENTMUX_ROUTER_BASE_URL or http://127.0.0.1:4001.",
    )
    ap.add_argument(
        "--litellm-base-url",
        default=DEFAULT_LITELLM_BASE_URL,
        help="LiteLLM base URL for strict E2E. Defaults to INTENTMUX_LITELLM_BASE_URL or http://127.0.0.1:4000.",
    )
    ap.add_argument(
        "--litellm-env",
        help="Optional env file to source before strict E2E. May also be set with INTENTMUX_LITELLM_ENV.",
    )
    ap.add_argument(
        "--log-container",
        default=os.getenv("INTENTMUX_LOG_CONTAINER", "intentmux"),
        help="Container name used by strict E2E log correlation.",
    )
    args = ap.parse_args()

    repo = path_from_arg_or_env(args.repo, "INTENTMUX_REPO", DEFAULT_REPO)
    log_dir = path_from_arg_or_env(args.log_dir, "INTENTMUX_LOG_DIR", DEFAULT_LOG_DIR)
    route_all_glob = (
        args.route_log_glob
        or os.getenv("INTENTMUX_ROUTE_LOG_GLOB")
        or str(log_dir / "routes" / "*.jsonl")
    )
    health_dir = log_dir / "health"
    litellm_env_raw = args.litellm_env or os.getenv("INTENTMUX_LITELLM_ENV")
    litellm_env = Path(litellm_env_raw).expanduser() if litellm_env_raw else None

    now, day = report_now_and_day(timezone_name=args.timezone, explicit_date=args.date)
    health_dir.mkdir(parents=True, exist_ok=True)

    commit = run("git rev-parse --short HEAD", cwd=repo, timeout=10)
    commit_id = commit["stdout"] if commit["ok"] else "unknown"

    # 1) ready
    code, payload, err = http_get_json(f"{args.router_base_url.rstrip('/')}/ready", timeout=5)
    ready_ok, ready_summary, ready_detail = parse_ready(payload, code, err)

    # 2) route summary (today)
    day_log = log_dir / "routes" / f"{day}.jsonl"
    if day_log.exists() and day_log.stat().st_size > 0:
        summary_today_cmd = (
            "uv run python scripts/router_log_summary.py "
            f"{shlex.quote(str(day_log))} --slow-request-limit {args.slow_request_limit}"
        )
        route_summary_today = run(summary_today_cmd, cwd=repo, timeout=90)
        summary_today_highlights = keep(
            (route_summary_today["stdout"] + "\n" + route_summary_today["stderr"]).strip(),
            [
                "total", "completed", "errors", "routes", "targets", "reasons", "outcomes",
                "not_ok", "upstream_statuses", "upstream_non_200", "max_duration_ms", "duration_ms", "p95", "p99", "slow_requests",
            ],
        )
    else:
        route_summary_today = {"ok": True, "exit_code": 0, "stdout": "no_samples", "stderr": ""}
        summary_today_highlights = ["no_samples: today route log missing or empty"]

    # 2b) route summary (all logs) - context only
    summary_all_cmd = (
        "uv run python scripts/router_log_summary.py "
        f"{route_all_glob} --slow-request-limit {args.slow_request_limit}"
    )
    route_summary_all = run(summary_all_cmd, cwd=repo, timeout=90)
    summary_all_highlights = keep(
        (route_summary_all["stdout"] + "\n" + route_summary_all["stderr"]).strip(),
        [
            "total", "completed", "errors", "routes", "targets", "reasons", "outcomes",
            "not_ok", "upstream_statuses", "upstream_non_200", "max_duration_ms", "duration_ms", "p95", "p99", "slow_requests",
        ],
    )

    # 3/4) budget (today only)
    traffic_evidence = traffic_evidence_from_day_log(
        day_log,
        min_records=args.min_route_records,
    )

    if budget_no_samples(day_log):
        strict = {"ok": True, "exit_code": 0, "stdout": "no_samples", "stderr": ""}
        tolerant = {"ok": True, "exit_code": 0, "stdout": "no_samples", "stderr": ""}
        strict_reasons = ["no_samples: strict budget skipped"]
        tolerant_reasons = ["no_samples: tolerant budget skipped"]
    else:
        strict_cmd = (
            "uv run python scripts/check_route_error_budget.py "
            f"{shlex.quote(str(day_log))} --min-total 1 --max-error-rate 0 --max-target-error-rate 0 "
            "--max-route-error-rate 0 --max-not-ok-rate 0 --max-embedding-error-rate 0 "
            "--max-upstream-status-rate 400=0"
        )
        strict = run(strict_cmd, cwd=repo, timeout=90)
        strict_reasons = keep(
            (strict["stdout"] + "\n" + strict["stderr"]).strip(),
            ["reason", "rate", "total", "fails", "failed", "no_samples"],
            no_truncate_keywords=("reasons:",),
        )

        tol_cmd = (
            "uv run python scripts/check_route_error_budget.py "
            f"{shlex.quote(str(day_log))} --min-total 1 --max-error-rate 0 --max-target-error-rate 0 "
            "--max-route-error-rate 0 --max-not-ok-rate 0.02 --max-embedding-error-rate 0.13 "
            "--max-upstream-status-rate 400=0.02"
        )
        tolerant = run(tol_cmd, cwd=repo, timeout=90)
        tolerant_reasons = keep(
            (tolerant["stdout"] + "\n" + tolerant["stderr"]).strip(),
            ["reason", "rate", "total", "fails", "failed", "no_samples"],
            no_truncate_keywords=("reasons:",),
        )

    # 5) e2e (optional)
    if args.run_e2e:
        e2e_cmd = build_e2e_cmd(
            litellm_base_url=args.litellm_base_url,
            log_container=args.log_container,
            litellm_env=litellm_env,
        )
        e2e = run(e2e_cmd, cwd=repo, timeout=240)
        e2e_mode = "strict"
    else:
        e2e = {"ok": True, "exit_code": 0, "stdout": "skipped by policy", "stderr": ""}
        e2e_mode = "skipped"
    e2e_highlights = keep(
        (e2e["stdout"] + "\n" + e2e["stderr"]).strip(),
        ["pass", "fail", "strict_request_id_matches", "route_id", "target_model", "log_redaction"],
        no_truncate_keywords=("strict_request_id_matches",),
    )

    report = {
        "time": now.isoformat(),
        "repo": str(repo),
        "commit": commit_id,
        "ready": {
            "ok": ready_ok,
            "summary": ready_summary,
            **ready_detail,
        },
        "route_summary_today": {
            "exit_code": route_summary_today["exit_code"],
            "highlights": summary_today_highlights,
            "log": str(day_log),
        },
        "route_summary_all_logs": {
            "exit_code": route_summary_all["exit_code"],
            "highlights": summary_all_highlights,
            "glob": route_all_glob,
        },
        "traffic_evidence": traffic_evidence,
        "strict_budget": {
            "exit_code": strict["exit_code"],
            "reasons": strict_reasons,
        },
        "tolerant_budget": {
            "exit_code": tolerant["exit_code"],
            "reasons": tolerant_reasons,
        },
        "e2e": {
            "mode": e2e_mode,
            "exit_code": e2e["exit_code"],
            "highlights": e2e_highlights,
        },
    }

    json_path = health_dir / f"intentmux-health-{day}.json"
    md_path = health_dir / f"intentmux-health-{day}.md"
    latest_json = health_dir / "intentmux-health-latest.json"
    latest_md = health_dir / "intentmux-health-latest.md"

    report["paths"] = {
        "json": str(json_path),
        "md": str(md_path),
        "latest_json": str(latest_json),
        "latest_md": str(latest_md),
    }

    json_text = json.dumps(report, ensure_ascii=False, indent=2)
    md_text = render_md(report)

    json_path.write_text(json_text + "\n", encoding="utf-8")
    md_path.write_text(md_text, encoding="utf-8")
    latest_json.write_text(json_text + "\n", encoding="utf-8")
    latest_md.write_text(md_text, encoding="utf-8")

    print(
        json.dumps(
            {
                "time": report["time"],
                "commit": report["commit"],
                "ready_ok": report["ready"]["ok"],
                "strict_exit": report["strict_budget"]["exit_code"],
                "tolerant_exit": report["tolerant_budget"]["exit_code"],
                "traffic_evidence_ok": report["traffic_evidence"]["ok"],
                "today_records": report["traffic_evidence"]["today_records"],
                "e2e_mode": report["e2e"]["mode"],
                "e2e_exit": report["e2e"]["exit_code"],
                "json": str(json_path),
                "md": str(md_path),
            },
            ensure_ascii=False,
        )
    )

    # non-zero when core checks fail (ready or both budgets fail)
    if not report["ready"]["ok"]:
        return 2
    if not report["traffic_evidence"]["ok"]:
        return 4
    if report["strict_budget"]["exit_code"] != 0 and report["tolerant_budget"]["exit_code"] != 0:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
