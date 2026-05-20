from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.replay_routes import load_replay_cases, render_markdown


def write_routes(path: Path) -> None:
    path.write_text(
        """
route_model: auto
fallback_route_id: lite
route_kernel: basic
threshold: 0.5
margin: 0.05
routes:
  lite:
    target_model: local-lite
    description: light
    utterances:
      - 翻译成中文
      - 总结这篇文章
  deep:
    target_model: local-deep
    description: hard
    utterances:
      - 分析这个线上 bug
      - 代码审查
hard_rules:
  - route_id: deep
    keywords:
      - 线上事故
""",
        encoding="utf-8",
    )


def test_load_replay_cases_reads_prompt_review_without_requiring_raw_output(tmp_path: Path):
    prompts = tmp_path / "prompts.jsonl"
    prompts.write_text(
        json.dumps(
            {
                "event": "prompt_review",
                "request_id": "req-1",
                "latest_user_text": "分析这个线上 bug",
                "route_id": "deep",
                "reason": "embedding",
                "target_model": "local-deep",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    cases = load_replay_cases([str(prompts)])

    assert cases == [
        {
            "id": "req-1",
            "request_id": "req-1",
            "text": "分析这个线上 bug",
            "reference_route": "deep",
            "reference_route_source": "historical_route_id",
            "source_event": "prompt_review",
            "historical_reason": "embedding",
            "historical_target_model": "local-deep",
            "truncated": False,
        }
    ]


def test_replay_routes_cli_compares_baselines_and_redacts_text_by_default(tmp_path: Path):
    routes = tmp_path / "routes.yaml"
    prompts = tmp_path / "prompts.jsonl"
    output = tmp_path / "replay.json"
    markdown = tmp_path / "replay.md"
    write_routes(routes)
    prompts.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "event": "prompt_review",
                        "request_id": "req-lite",
                        "latest_user_text": "翻译成中文",
                        "route_id": "lite",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "event": "prompt_review",
                        "request_id": "req-deep",
                        "latest_user_text": "分析这个线上 bug",
                        "route_id": "deep",
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            "scripts/replay_routes.py",
            str(prompts),
            "--routes",
            str(routes),
            "--mock-embeddings",
            "--json-output",
            str(output),
            "--markdown-output",
            str(markdown),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema"] == "intentmux-route-replay-v1"
    assert payload["summary"]["case_count"] == 2
    assert payload["summary"]["raw_text_included"] is False
    assert payload["summary"]["remote_embeddings_allowed"] is False
    assert payload["summary"]["reference_route_sources"] == {"historical_route_id": 2}
    assert payload["summary"]["baseline_routes"]["current-router"] == {"deep": 1, "lite": 1}
    assert payload["summary"]["baseline_routes"]["always-lite"] == {"lite": 2}
    assert payload["summary"]["baseline_reference_agreement"]["current-router"] == 2
    assert payload["summary"]["baseline_reference_agreement_by_source"]["current-router"] == {
        "historical_route_id": 2
    }
    deep_decision = payload["cases"][1]["decisions"]["current-router"]
    assert deep_decision["top_route_id"] == "deep"
    assert deep_decision["second_route_id"] == "lite"
    assert deep_decision["threshold"] == 0.5
    assert deep_decision["margin"] == 0.05
    assert deep_decision["match_source"] == "inline_config"
    assert deep_decision["match_text_sha256"]
    assert "text" not in payload["cases"][0]
    assert payload["cases"][0]["text_sha256"]
    markdown_text = markdown.read_text(encoding="utf-8")
    assert "top_route" in markdown_text
    assert "match_text_sha256" in markdown_text
    assert "inline_config" in markdown_text
    assert "翻译成中文" not in markdown_text


def test_render_markdown_warns_historical_routes_are_not_ground_truth():
    markdown = render_markdown(
        {
            "summary": {
                "case_count": 1,
                "reference_routes": {"lite": 1},
                "reference_route_sources": {"historical_route_id": 1},
                "baseline_routes": {"current-router": {"lite": 1}},
                "baseline_reference_agreement": {"current-router": 1},
                "baseline_reference_agreement_by_source": {
                    "current-router": {"historical_route_id": 1}
                },
                "raw_text_included": False,
                "remote_embeddings_allowed": False,
            },
            "cases": [
                {
                    "id": "req-1",
                    "reference_route": "lite",
                    "reference_route_source": "historical_route_id",
                    "text_sha256": "abc",
                    "text_chars": 3,
                    "decisions": {
                        "current-router": {
                            "route_id": "lite",
                            "reason": "embedding",
                            "score": 0.8,
                            "threshold": 0.5,
                            "margin": 0.05,
                            "top_route_id": "lite",
                            "second_route_id": "deep",
                            "match_source": "inline_config",
                            "match_index": 0,
                            "match_text_sha256": "match-sha",
                        }
                    },
                }
            ],
        }
    )

    assert "not ground truth" in markdown


def test_replay_routes_prefers_explicit_label_over_historical_route(tmp_path: Path):
    routes = tmp_path / "routes.yaml"
    prompts = tmp_path / "prompts.jsonl"
    output = tmp_path / "replay.json"
    write_routes(routes)
    prompts.write_text(
        json.dumps(
            {
                "event": "prompt_review",
                "request_id": "req-corrected",
                "latest_user_text": "分析这个线上 bug",
                "route_id": "lite",
                "expect": "deep",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            "scripts/replay_routes.py",
            str(prompts),
            "--routes",
            str(routes),
            "--mock-embeddings",
            "--json-output",
            str(output),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["cases"][0]["reference_route"] == "deep"
    assert payload["cases"][0]["reference_route_source"] == "explicit_label"
    assert payload["summary"]["reference_route_sources"] == {"explicit_label": 1}
    assert payload["summary"]["baseline_reference_agreement_by_source"]["current-router"] == {
        "explicit_label": 1
    }


def test_replay_routes_blocks_remote_embeddings_by_default(tmp_path: Path):
    routes = tmp_path / "routes.yaml"
    prompts = tmp_path / "prompts.jsonl"
    write_routes(routes)
    text = routes.read_text(encoding="utf-8")
    routes.write_text(
        text.replace(
            "route_kernel: basic",
            "route_kernel: basic\nembedding_url: https://embedding.example.com/v1/embeddings",
        ),
        encoding="utf-8",
    )
    prompts.write_text(
        json.dumps(
            {
                "event": "prompt_review",
                "request_id": "req-remote",
                "latest_user_text": "翻译成中文",
                "route_id": "lite",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/replay_routes.py",
            str(prompts),
            "--routes",
            str(routes),
        ],
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "non-local embedding endpoint" in result.stderr


def test_replay_routes_stdout_is_compact_and_redacted_by_default(tmp_path: Path):
    routes = tmp_path / "routes.yaml"
    prompts = tmp_path / "prompts.jsonl"
    write_routes(routes)
    prompts.write_text(
        json.dumps(
            {
                "event": "prompt_review",
                "request_id": "req-private",
                "latest_user_text": "PRIVATE PROMPT MUST NOT HIT STDOUT",
                "route_id": "lite",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/replay_routes.py",
            str(prompts),
            "--routes",
            str(routes),
            "--mock-embeddings",
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    payload = json.loads(result.stdout)
    assert payload["schema"] == "intentmux-route-replay-summary-v1"
    assert payload["case_count"] == 1
    assert payload["raw_text_included"] is False
    assert "cases" not in payload
    assert "PRIVATE PROMPT" not in result.stdout


def test_replay_routes_include_text_requires_explicit_output_file(tmp_path: Path):
    routes = tmp_path / "routes.yaml"
    prompts = tmp_path / "prompts.jsonl"
    write_routes(routes)
    prompts.write_text(
        json.dumps(
            {
                "event": "prompt_review",
                "request_id": "req-private",
                "latest_user_text": "PRIVATE PROMPT MUST NOT HIT STDERR",
                "route_id": "lite",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/replay_routes.py",
            str(prompts),
            "--routes",
            str(routes),
            "--mock-embeddings",
            "--include-text",
        ],
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "--include-text requires --json-output or --markdown-output" in result.stderr
    assert "PRIVATE PROMPT" not in result.stdout
    assert "PRIVATE PROMPT" not in result.stderr
