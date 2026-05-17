# AI Review Packet V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first learnable-routing loop artifact: a generic local-only packet for an external AI reviewer and a structured AI review summary, without changing runtime routing policy.

**Architecture:** Reuse `scripts/select_review_candidates.py` as the deterministic candidate source. Add one script that transforms candidate JSON into an AI-readable packet, and one script that validates AI output and renders a human-auditable summary. IntentMux does not run the AI reviewer inside the request-time runtime; keep AI runner integration outside the public repo, and do not require Retinue, Hermes, OpenCode, or RayStorm paths.

**Tech Stack:** Python 3.11, stdlib JSON/argparse/pathlib, pytest, existing IntentMux JSON candidate reports.

---

## Scope

This plan implements only `docs/PROJECT_CONTROL.md` work item 2:

```text
Add a generic local-only AI review packet. It must not require RayStorm,
Hermes, Retinue, or OpenCode.
```

It intentionally does not:

- change routing policy;
- tune threshold or margin;
- modify route bank assets;
- wire daily health;
- call an LLM provider;
- run an AI reviewer inside IntentMux runtime;
- depend on Retinue/Hermes/OpenCode;
- put raw prompt text into default artifacts.

## Files

- Create: `scripts/prepare_ai_review_packet.py`
  - Reads candidate JSON from `scripts/select_review_candidates.py`.
  - Optionally reads prompt review logs by `request_id`.
  - Writes JSON and Markdown packet for any downstream AI runner.
  - Defaults to metadata-only output.
- Create: `scripts/summarize_ai_review.py`
  - Reads a structured AI review result JSON.
  - Validates allowed decisions, routes, confidence values, and no raw prompt leakage by default.
  - Writes JSON and Markdown summary for human audit.
- Create: `tests/test_ai_review_packet.py`
  - Tests packet grouping, privacy defaults, explicit raw-local inclusion, and markdown output.
- Create: `tests/test_summarize_ai_review.py`
  - Tests result validation, summary counts, escalation sections, and privacy guardrails.
- Modify: `docs/log_driven_quality_loop.md`
  - Add CLI examples for packet preparation and AI summary validation.
- Modify: `README.md`
  - Add a short pointer from log audit section to the new scripts.

## Data Contracts

### AI Review Packet JSON

Top-level shape:

```json
{
  "schema_version": "intentmux.ai_review_packet.v1",
  "privacy_mode": "metadata_only",
  "instructions": {
    "language": "zh-CN",
    "task": "Review IntentMux route candidates and summarize only actionable routing-quality findings.",
    "rules": [
      "Do not invent route labels.",
      "Escalate uncertainty instead of guessing.",
      "Do not suggest production policy changes without evidence."
    ]
  },
  "summary": {
    "candidate_count": 3,
    "groups": {
      "needs_human_decision": 1,
      "likely_regression_case": 1,
      "watch_only": 1,
      "privacy_blocked": 0
    }
  },
  "candidates": [
    {
      "group": "needs_human_decision",
      "request_id": "req-1",
      "route_id": "deep",
      "target_model": "pro-router",
      "reason": "hard_rule:token",
      "review_reasons": ["hard_rule"],
      "prompt_review": {"matched": true, "truncated": false, "text_chars": 120},
      "prompt_excerpt": null
    }
  ]
}
```

Groups:

- `needs_human_decision`: hard rule, route error, upstream non-2xx, embedding error.
- `likely_regression_case`: low-confidence or near-margin candidate with matched non-truncated prompt review evidence.
- `watch_only`: low-confidence or near-margin candidate without enough prompt evidence.
- `privacy_blocked`: prompt review exists but is truncated, or raw prompt text would be required before deciding.

Default packet output must not contain `latest_user_text`, raw request body, completion text, bearer token, API key, or provider key.

### AI Review Result JSON

Input accepted by `summarize_ai_review.py`:

```json
{
  "schema_version": "intentmux.ai_review_result.v1",
  "items": [
    {
      "request_id": "req-1",
      "agent_decision": "needs_human",
      "confidence": "medium",
      "suggested_expected_route": "deep",
      "summary_zh": "hard rule 命中 token，可能需要确认是否过宽。",
      "evidence": ["reason=hard_rule:token", "prompt_review.matched=true"],
      "human_decision_required": true,
      "redaction_required": false
    }
  ]
}
```

Allowed values:

- `agent_decision`: `route_ok`, `suspected_misroute`, `needs_human`, `privacy_blocked`, `watch_only`
- `confidence`: `high`, `medium`, `low`
- `suggested_expected_route`: `lite`, `deep`, `unknown`

Summary output must surface:

- decision counts;
- confidence counts;
- high-priority human audit items;
- suspected regression cases;
- privacy-blocked cases;
- route suggestions by `lite` / `deep` / `unknown`.

## Task 1: Packet Preparation Tests

**Files:**

- Create: `tests/test_ai_review_packet.py`

- [x] **Step 1: Add tests for metadata-only grouping**

Add tests that call the script functions directly:

```python
from scripts.prepare_ai_review_packet import build_ai_review_packet


def test_build_ai_review_packet_groups_candidates_without_prompt_text():
    candidate_report = {
        "summary": {"candidate_count": 4},
        "candidates": [
            {
                "request_id": "hard",
                "route_id": "deep",
                "target_model": "pro",
                "reason": "hard_rule:token",
                "review_reasons": ["hard_rule"],
                "prompt_review": {"matched": True, "truncated": False, "text_chars": 20},
            },
            {
                "request_id": "low",
                "route_id": "lite",
                "target_model": "cheap",
                "reason": "low_confidence",
                "review_reasons": ["low_confidence", "near_margin"],
                "prompt_review": {"matched": True, "truncated": False, "text_chars": 30},
            },
            {
                "request_id": "watch",
                "route_id": "lite",
                "target_model": "cheap",
                "reason": "low_confidence",
                "review_reasons": ["low_confidence"],
            },
            {
                "request_id": "truncated",
                "route_id": "lite",
                "target_model": "cheap",
                "reason": "low_confidence",
                "review_reasons": ["low_confidence"],
                "prompt_review": {"matched": True, "truncated": True, "text_chars": 20000},
            },
        ],
    }

    packet = build_ai_review_packet(candidate_report)

    assert packet["schema_version"] == "intentmux.ai_review_packet.v1"
    assert packet["privacy_mode"] == "metadata_only"
    assert packet["summary"]["groups"] == {
        "needs_human_decision": 1,
        "likely_regression_case": 1,
        "privacy_blocked": 1,
        "watch_only": 1,
    }
    assert [item["group"] for item in packet["candidates"]] == [
        "needs_human_decision",
        "likely_regression_case",
        "watch_only",
        "privacy_blocked",
    ]
    assert "latest_user_text" not in str(packet)
    assert all(item["prompt_excerpt"] is None for item in packet["candidates"])
```

- [x] **Step 2: Add tests for explicit raw-local prompt excerpts**

```python
from scripts.prepare_ai_review_packet import build_ai_review_packet


def test_build_ai_review_packet_includes_excerpt_only_when_raw_local_enabled():
    candidate_report = {
        "summary": {"candidate_count": 1},
        "candidates": [
            {
                "request_id": "req-1",
                "route_id": "lite",
                "target_model": "cheap",
                "reason": "low_confidence",
                "review_reasons": ["low_confidence"],
                "prompt_review": {"matched": True, "truncated": False, "text_chars": 12},
            }
        ],
    }
    prompt_records = [
        {
            "event": "prompt_review",
            "request_id": "req-1",
            "latest_user_text": "请分析这个问题",
        }
    ]

    metadata_only = build_ai_review_packet(candidate_report, prompt_records=prompt_records)
    raw_local = build_ai_review_packet(
        candidate_report,
        prompt_records=prompt_records,
        include_prompt_text="raw_local",
        max_prompt_chars=5,
    )

    assert metadata_only["candidates"][0]["prompt_excerpt"] is None
    assert raw_local["privacy_mode"] == "raw_local"
    assert raw_local["candidates"][0]["prompt_excerpt"] == "请分析这个"
```

- [x] **Step 3: Add CLI smoke test**

```python
import json
import sys

from scripts import prepare_ai_review_packet


def test_prepare_ai_review_packet_cli_writes_json_and_markdown(tmp_path, monkeypatch):
    input_path = tmp_path / "candidates.json"
    json_output = tmp_path / "packet.json"
    md_output = tmp_path / "packet.md"
    input_path.write_text(
        json.dumps(
            {
                "summary": {"candidate_count": 1},
                "candidates": [
                    {
                        "request_id": "req-1",
                        "route_id": "lite",
                        "target_model": "cheap",
                        "reason": "low_confidence",
                        "review_reasons": ["low_confidence"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prepare_ai_review_packet.py",
            "--input",
            str(input_path),
            "--json-output",
            str(json_output),
            "--markdown-output",
            str(md_output),
        ],
    )

    prepare_ai_review_packet.main()

    assert json.loads(json_output.read_text(encoding="utf-8"))["schema_version"] == "intentmux.ai_review_packet.v1"
    assert "AI Review Packet" in md_output.read_text(encoding="utf-8")
```

- [x] **Step 4: Run failing tests**

Run:

```bash
uv run pytest tests/test_ai_review_packet.py -q
```

Expected: import failure for `scripts.prepare_ai_review_packet`.

## Task 2: Packet Preparation Implementation

**Files:**

- Create: `scripts/prepare_ai_review_packet.py`

- [x] **Step 1: Implement packet builder**

Create a focused script with:

- `load_json(path: Path) -> dict[str, Any]`
- `prompt_text_index(prompt_records: Iterable[dict[str, Any]]) -> dict[str, str]`
- `group_candidate(candidate: dict[str, Any]) -> str`
- `build_ai_review_packet(...) -> dict[str, Any]`
- `render_markdown(packet: dict[str, Any]) -> str`
- `main() -> None`

Implementation rules:

- hard rule, route error, upstream non-2xx, embedding error -> `needs_human_decision`
- prompt review truncated -> `privacy_blocked`
- low-confidence or near-margin with matched prompt evidence -> `likely_regression_case`
- otherwise -> `watch_only`
- default prompt excerpt is `None`
- raw prompt excerpts require `--include-prompt-text raw_local`

- [x] **Step 2: Run packet tests**

Run:

```bash
uv run pytest tests/test_ai_review_packet.py -q
```

Expected: all tests pass.

## Task 3: AI Summary Tests

**Files:**

- Create: `tests/test_summarize_ai_review.py`

- [x] **Step 1: Add validation and summary tests**

```python
import json
import sys

import pytest

from scripts import summarize_ai_review
from scripts.summarize_ai_review import ReviewResultError, summarize_review_result


def test_summarize_review_result_counts_and_surfaces_human_items():
    result = {
        "schema_version": "intentmux.ai_review_result.v1",
        "items": [
            {
                "request_id": "req-human",
                "agent_decision": "needs_human",
                "confidence": "medium",
                "suggested_expected_route": "deep",
                "summary_zh": "需要确认 hard rule 是否过宽。",
                "evidence": ["reason=hard_rule:token"],
                "human_decision_required": True,
                "redaction_required": False,
            },
            {
                "request_id": "req-misroute",
                "agent_decision": "suspected_misroute",
                "confidence": "high",
                "suggested_expected_route": "lite",
                "summary_zh": "普通解释请求疑似不该升级。",
                "evidence": ["route_id=deep"],
                "human_decision_required": False,
                "redaction_required": True,
            },
        ],
    }

    summary = summarize_review_result(result)

    assert summary["summary"]["decision_counts"] == {
        "needs_human": 1,
        "suspected_misroute": 1,
    }
    assert summary["human_audit_items"][0]["request_id"] == "req-human"
    assert summary["suspected_regression_cases"][0]["request_id"] == "req-misroute"
```

- [x] **Step 2: Add rejection tests**

```python
import pytest

from scripts.summarize_ai_review import ReviewResultError, summarize_review_result


def test_summarize_review_result_rejects_unknown_decision():
    with pytest.raises(ReviewResultError, match="agent_decision"):
        summarize_review_result(
            {
                "schema_version": "intentmux.ai_review_result.v1",
                "items": [
                    {
                        "request_id": "req-1",
                        "agent_decision": "invented",
                        "confidence": "high",
                        "suggested_expected_route": "unknown",
                        "summary_zh": "bad",
                        "evidence": [],
                        "human_decision_required": False,
                        "redaction_required": False,
                    }
                ],
            }
        )


def test_summarize_review_result_rejects_raw_prompt_keys():
    with pytest.raises(ReviewResultError, match="raw prompt"):
        summarize_review_result(
            {
                "schema_version": "intentmux.ai_review_result.v1",
                "items": [
                    {
                        "request_id": "req-1",
                        "agent_decision": "watch_only",
                        "confidence": "low",
                        "suggested_expected_route": "unknown",
                        "summary_zh": "bad",
                        "evidence": [],
                        "latest_user_text": "should not be here",
                        "human_decision_required": False,
                        "redaction_required": False,
                    }
                ],
            }
        )
```

- [x] **Step 3: Add CLI smoke test**

```python
def test_summarize_ai_review_cli_writes_json_and_markdown(tmp_path, monkeypatch):
    input_path = tmp_path / "ai-result.json"
    json_output = tmp_path / "summary.json"
    md_output = tmp_path / "summary.md"
    input_path.write_text(
        json.dumps(
            {
                "schema_version": "intentmux.ai_review_result.v1",
                "items": [
                    {
                        "request_id": "req-1",
                        "agent_decision": "watch_only",
                        "confidence": "low",
                        "suggested_expected_route": "unknown",
                        "summary_zh": "继续观察。",
                        "evidence": ["reason=low_confidence"],
                        "human_decision_required": False,
                        "redaction_required": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "summarize_ai_review.py",
            "--input",
            str(input_path),
            "--json-output",
            str(json_output),
            "--markdown-output",
            str(md_output),
        ],
    )

    summarize_ai_review.main()

    assert json.loads(json_output.read_text(encoding="utf-8"))["schema_version"] == "intentmux.ai_review_summary.v1"
    assert "AI Review Summary" in md_output.read_text(encoding="utf-8")
```

- [x] **Step 4: Run failing tests**

Run:

```bash
uv run pytest tests/test_summarize_ai_review.py -q
```

Expected: import failure for `scripts.summarize_ai_review`.

## Task 4: AI Summary Implementation

**Files:**

- Create: `scripts/summarize_ai_review.py`

- [x] **Step 1: Implement validator and summary builder**

Create:

- `ReviewResultError(ValueError)`
- `summarize_review_result(result: dict[str, Any]) -> dict[str, Any]`
- `render_markdown(summary: dict[str, Any]) -> str`
- `main() -> None`

Validation rules:

- top-level `items` must be a list;
- reject raw prompt keys: `latest_user_text`, `prompt`, `messages`, `completion`, `request_body`;
- enforce allowed values for `agent_decision`, `confidence`, and `suggested_expected_route`;
- require `request_id` and `summary_zh` strings;
- require `evidence` to be a list of strings.

- [x] **Step 2: Run summary tests**

Run:

```bash
uv run pytest tests/test_summarize_ai_review.py -q
```

Expected: all tests pass.

## Task 5: Documentation

**Files:**

- Modify: `docs/log_driven_quality_loop.md`
- Modify: `README.md`

- [x] **Step 1: Document the packet flow**

Add a concise section after review candidate selection. Use this content:

````markdown
## AI Review Packet

Generate a local-only packet for an AI reviewer:

```bash
uv run python scripts/prepare_ai_review_packet.py \
  --input /data/reviews/intentmux-review-candidates-YYYY-MM-DD.json \
  --json-output /data/reviews/agent/intentmux-ai-review-packet-YYYY-MM-DD.json \
  --markdown-output /data/reviews/agent/intentmux-ai-review-packet-YYYY-MM-DD.md
```

The default packet is metadata-only. Raw prompt excerpts require the explicit
`--include-prompt-text raw_local` flag and should only be written under a local
private runtime directory.

Validate and summarize AI output:

```bash
uv run python scripts/summarize_ai_review.py \
  --input /data/reviews/agent/intentmux-ai-review-result-YYYY-MM-DD.json \
  --json-output /data/reviews/agent/intentmux-ai-review-summary-YYYY-MM-DD.json \
  --markdown-output /data/reviews/agent/intentmux-ai-review-summary-YYYY-MM-DD.md
```
````

- [x] **Step 2: Add README pointer**

Add one paragraph in the log audit section that points to the new packet and summary scripts. Keep it short.

## Task 6: Final Verification

**Files:** no code changes.

- [x] **Step 1: Run focused tests**

```bash
uv run pytest tests/test_ai_review_packet.py tests/test_summarize_ai_review.py tests/test_select_review_candidates.py tests/test_import_review_samples.py -q
```

Expected: all tests pass.

- [x] **Step 2: Run lint**

```bash
uv run python -m ruff check .
```

Expected: `All checks passed!`

- [x] **Step 3: Run route contract**

```bash
uv run python scripts/verify_route_contract.py
```

Expected: `Route contract verification passed.`

- [x] **Step 4: Commit**

```bash
git add scripts/prepare_ai_review_packet.py scripts/summarize_ai_review.py tests/test_ai_review_packet.py tests/test_summarize_ai_review.py README.md docs/PROJECT_CONTROL.md docs/log_driven_quality_loop.md docs/superpowers/plans/README.md docs/archive/plans/2026-05-18-ai-review-packet-v1.md
git commit -m "feat: add AI review packet workflow"
```

## Self-Review

- Spec coverage: covers `PROJECT_CONTROL.md` active work item 2 only.
- Scope: does not wire daily health; that should be a separate plan after this lands.
- Privacy: default packet is metadata-only; raw prompt excerpts require explicit local flag.
- Product boundary: no Retinue/Hermes/OpenCode dependency.
- Testing: tests cover packet grouping, prompt privacy, result validation, CLI outputs, and existing candidate/import scripts.
