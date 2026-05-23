from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.eval_routes import (
    EvalCase,
    EvalQueryEmbeddingCache,
    load_cases,
    run_eval,
    text_sha256,
    validate_case_route_ids,
)


def test_validate_case_route_ids_accepts_known_route_id():
    validate_case_route_ids([EvalCase(text="hi", expect="lite")], {"lite", "deep"})


def test_validate_case_route_ids_rejects_target_model_name():
    with pytest.raises(ValueError, match="deep-upstream"):
        validate_case_route_ids([EvalCase(text="hi", expect="deep-upstream")], {"lite", "deep"})


def test_load_cases_ignores_eval_builder_metadata(tmp_path: Path):
    cases = tmp_path / "cases.yaml"
    cases.write_text(
        """
cases:
  - id: lite_001
    slice: lite_general_zh
    text: 帮我总结这段话
    expect: lite
    source: curated
    rationale: 普通总结请求低风险，适合 lite。
""",
        encoding="utf-8",
    )

    assert load_cases(cases) == [
        EvalCase(
            id="lite_001",
            slice="lite_general_zh",
            text="帮我总结这段话",
            expect="lite",
            source="curated",
        )
    ]


def test_load_cases_preserves_long_context_metadata(tmp_path: Path):
    cases = tmp_path / "cases.yaml"
    cases.write_text(
        """
cases:
  - id: long_001
    slice: deep_long_context_zh
    text: 请基于长文档定位冲突结论
    expect: deep
    source: curated
    input_chars: 12000
    message_count: 3
    context_policy: preserved_length
""",
        encoding="utf-8",
    )

    assert load_cases(cases) == [
        EvalCase(
            id="long_001",
            slice="deep_long_context_zh",
            text="请基于长文档定位冲突结论",
            expect="deep",
            source="curated",
            input_chars=12000,
            message_count=3,
            context_policy="preserved_length",
        )
    ]


def test_eval_routes_json_output_includes_id_slice_and_scores(tmp_path: Path):
    cases = tmp_path / "cases.yaml"
    output = tmp_path / "eval.json"
    cases.write_text(
        """
cases:
  - id: deep_code_001
    slice: deep_code_zh
    text: 这个 PR 会不会引入回归
    expect: deep
    source: test
""",
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            "scripts/eval_routes.py",
            "--cases",
            str(cases),
            "--mock-embeddings",
            "--json-output",
            str(output),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema"] == "intentmux-route-eval-v1"
    assert payload["cases"][0]["id"] == "deep_code_001"
    assert payload["cases"][0]["slice"] == "deep_code_zh"
    assert payload["cases"][0]["expect"] == "deep"
    assert payload["cases"][0]["actual_route"] == "deep"
    assert payload["cases"][0]["passed"] is True
    assert "text" not in payload["cases"][0]
    assert payload["cases"][0]["text_sha256"]
    assert payload["cases"][0]["text_chars"] == len("这个 PR 会不会引入回归")
    assert "score" in payload["cases"][0]
    assert "second_score" in payload["cases"][0]
    assert "score_margin" in payload["cases"][0]
    assert payload["cases"][0]["threshold"] == 0.4
    assert payload["cases"][0]["margin"] == 0.04
    assert payload["cases"][0]["top_route_id"] == "deep"
    assert "second_route_id" in payload["cases"][0]
    assert payload["cases"][0]["match_source"] is not None
    assert payload["cases"][0]["match_text_sha256"] is not None


def test_eval_routes_json_output_preserves_long_context_metadata(tmp_path: Path):
    cases = tmp_path / "cases.yaml"
    output = tmp_path / "eval.json"
    cases.write_text(
        """
cases:
  - id: long_001
    slice: deep_long_context_zh
    text: 线上长文档分析是否存在数据损坏风险
    expect: deep
    source: test
    input_chars: 12000
    message_count: 3
    context_policy: preserved_length
""",
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            "scripts/eval_routes.py",
            "--cases",
            str(cases),
            "--mock-embeddings",
            "--json-output",
            str(output),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    case = json.loads(output.read_text(encoding="utf-8"))["cases"][0]
    assert case["slice"] == "deep_long_context_zh"
    assert case["input_chars"] == 12000
    assert case["message_count"] == 3
    assert case["context_policy"] == "preserved_length"


def test_mock_eval_keeps_generic_advice_on_lite(tmp_path: Path):
    cases = tmp_path / "cases.yaml"
    output = tmp_path / "eval.json"
    cases.write_text(
        """
cases:
  - id: lite_general_advice_001
    slice: lite_general_zh
    text: 这个学习计划靠谱吗？
    expect: lite
    source: regression
""",
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            "scripts/eval_routes.py",
            "--cases",
            str(cases),
            "--mock-embeddings",
            "--json-output",
            str(output),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    case = json.loads(output.read_text(encoding="utf-8"))["cases"][0]
    assert case["actual_route"] == "lite"


def test_eval_routes_always_lite_baseline_routes_every_case_to_lite(tmp_path: Path):
    cases = tmp_path / "cases.yaml"
    output = tmp_path / "eval.json"
    cases.write_text(
        """
cases:
  - id: simple_001
    text: 帮我总结这段话
    expect: lite
  - id: hard_001
    text: 生产事故需要回滚
    expect: deep
""",
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            "scripts/eval_routes.py",
            "--cases",
            str(cases),
            "--baseline",
            "always-lite",
            "--json-output",
            str(output),
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["baseline"] == "always-lite"
    assert [case["actual_route"] for case in payload["cases"]] == ["lite", "lite"]
    assert [case["baseline"] for case in payload["cases"]] == ["always-lite", "always-lite"]


def test_eval_routes_always_deep_baseline_routes_every_case_to_deep(tmp_path: Path):
    cases = tmp_path / "cases.yaml"
    output = tmp_path / "eval.json"
    cases.write_text(
        """
cases:
  - id: simple_001
    text: 帮我总结这段话
    expect: lite
  - id: hard_001
    text: 生产事故需要回滚
    expect: deep
""",
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            "scripts/eval_routes.py",
            "--cases",
            str(cases),
            "--baseline",
            "always-deep",
            "--json-output",
            str(output),
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["baseline"] == "always-deep"
    assert [case["actual_route"] for case in payload["cases"]] == ["deep", "deep"]


def test_eval_routes_hard_rule_only_baseline_uses_hard_rules_then_fallback(tmp_path: Path):
    cases = tmp_path / "cases.yaml"
    output = tmp_path / "eval.json"
    cases.write_text(
        """
cases:
  - id: simple_001
    text: 帮我总结这段话
    expect: lite
  - id: hard_001
    text: 生产事故需要回滚
    expect: deep
""",
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            "scripts/eval_routes.py",
            "--cases",
            str(cases),
            "--baseline",
            "hard-rule-only",
            "--json-output",
            str(output),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["baseline"] == "hard-rule-only"
    assert [
        (case["actual_route"], case["reason"])
        for case in payload["cases"]
    ] == [
        ("lite", "baseline:fallback"),
        ("deep", "baseline:hard_rule:生产事故"),
    ]


def test_eval_routes_embedding_only_baseline_ignores_hard_rules(tmp_path: Path):
    cases = tmp_path / "cases.yaml"
    output = tmp_path / "eval.json"
    cases.write_text(
        """
cases:
  - id: hard_rule_keyword_only
    text: 生产事故
    expect: deep
""",
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            "scripts/eval_routes.py",
            "--cases",
            str(cases),
            "--baseline",
            "embedding-only",
            "--mock-embeddings",
            "--json-output",
            str(output),
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["baseline"] == "embedding-only"
    assert payload["cases"][0]["reason"] != "hard_rule:生产事故"


def test_eval_routes_json_records_threshold_and_margin_overrides(tmp_path: Path):
    cases = tmp_path / "cases.yaml"
    output = tmp_path / "eval.json"
    cases.write_text(
        """
cases:
  - id: simple_001
    text: 帮我总结这段话
    expect: lite
""",
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            "scripts/eval_routes.py",
            "--cases",
            str(cases),
            "--threshold",
            "0.42",
            "--margin",
            "0.07",
            "--mock-embeddings",
            "--json-output",
            str(output),
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["threshold"] == 0.42
    assert payload["margin"] == 0.07


def test_eval_routes_stdout_redacts_case_text_by_default(tmp_path: Path):
    cases = tmp_path / "cases.yaml"
    cases.write_text(
        """
cases:
  - id: private_001
    text: PRIVATE EVAL PROMPT MUST NOT HIT STDOUT
    expect: lite
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/eval_routes.py",
            "--cases",
            str(cases),
            "--mock-embeddings",
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    assert "private_001" in result.stdout
    assert "PRIVATE EVAL PROMPT" not in result.stdout


def test_eval_routes_include_text_is_explicit(tmp_path: Path):
    cases = tmp_path / "cases.yaml"
    cases.write_text(
        """
cases:
  - id: private_001
    text: PRIVATE EVAL PROMPT MAY HIT STDOUT EXPLICITLY
    expect: lite
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/eval_routes.py",
            "--cases",
            str(cases),
            "--mock-embeddings",
            "--include-text",
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    assert "PRIVATE EVAL PROMPT MAY HIT STDOUT EXPLICITLY" in result.stdout


def test_eval_routes_json_include_text_is_explicit(tmp_path: Path):
    cases = tmp_path / "cases.yaml"
    output = tmp_path / "eval.json"
    cases.write_text(
        """
cases:
  - id: private_001
    text: PRIVATE EVAL PROMPT MAY HIT JSON EXPLICITLY
    expect: lite
""",
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            "scripts/eval_routes.py",
            "--cases",
            str(cases),
            "--mock-embeddings",
            "--json-output",
            str(output),
            "--include-text",
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    case = json.loads(output.read_text(encoding="utf-8"))["cases"][0]
    assert case["text"] == "PRIVATE EVAL PROMPT MAY HIT JSON EXPLICITLY"


def test_eval_routes_stdout_limit_bounds_terminal_rows(tmp_path: Path):
    cases = tmp_path / "cases.yaml"
    cases.write_text(
        """
cases:
  - id: case_1
    text: first text
    expect: lite
  - id: case_2
    text: second text
    expect: lite
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/eval_routes.py",
            "--cases",
            str(cases),
            "--mock-embeddings",
            "--stdout-limit",
            "1",
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    assert "case_1" in result.stdout
    assert "case_2" not in result.stdout
    assert "suppressed 1 eval row" in result.stdout


@pytest.mark.asyncio
async def test_eval_routes_reuses_persisted_eval_query_embeddings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    calls: list[list[str]] = []

    class FakeOpenAIEmbeddingClient:
        def __init__(
            self,
            url: str,
            model: str,
            timeout: float = 20.0,
            batch_size: int = 128,
            api_key: str | None = None,
            headers: dict[str, str] | None = None,
        ):
            pass

        async def embed(self, texts: list[str]) -> list[list[float]]:
            calls.append(list(texts))
            return [
                [1.0, 0.0] if "simple" in text else [0.0, 1.0]
                for text in texts
            ]

    monkeypatch.setattr(
        "scripts.eval_routes.OpenAIEmbeddingClient", FakeOpenAIEmbeddingClient
    )
    routes = tmp_path / "routes.yaml"
    route_cache = tmp_path / "route-embeddings.json"
    routes.write_text(
        f"""
route_model: auto
fallback_route_id: lite
route_kernel: basic
threshold: 0.1
margin: 0.0
embedding_url: http://127.0.0.1:1234/v1/embeddings
embedding_model: local-embedding
route_embedding_cache_path: {route_cache}
routes:
  lite:
    target_model: cheap-router
    description: simple requests
    utterances:
      - simple request
  deep:
    target_model: pro-router
    description: hard requests
    utterances:
      - hard request
""",
        encoding="utf-8",
    )
    cases = tmp_path / "cases.yaml"
    cases.write_text(
        """
cases:
  - id: simple_001
    text: simple request
    expect: lite
""",
        encoding="utf-8",
    )

    query_cache = tmp_path / "eval-query-embeddings.json"

    assert (
        await run_eval(
            cases,
            routes,
            mock_embeddings=False,
            eval_query_cache_path=query_cache,
        )
        == 0
    )
    assert query_cache.exists()
    cache_text = query_cache.read_text(encoding="utf-8")
    assert "simple request" not in cache_text
    assert "hard request" not in cache_text
    calls.clear()

    assert (
        await run_eval(
            cases,
            routes,
            mock_embeddings=False,
            eval_query_cache_path=query_cache,
        )
        == 0
    )

    assert calls == []


@pytest.mark.asyncio
async def test_eval_query_embedding_cache_invalidates_on_model_change(tmp_path: Path):
    cache_path = tmp_path / "eval-query-embeddings.json"
    cache_path.write_text(
        json.dumps(
            {
                "version": 1,
                "embedding_model": "old-model",
                "items": {text_sha256("simple request"): [9.0, 9.0]},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    class FakeEmbeddingClient:
        async def embed(self, texts: list[str]) -> list[list[float]]:
            return [[1.0, 0.0] for _ in texts]

    cache = EvalQueryEmbeddingCache(FakeEmbeddingClient(), cache_path, "new-model")

    assert await cache.embed(["simple request"]) == [[1.0, 0.0]]

    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    assert payload["embedding_model"] == "new-model"
    assert payload["items"] == {text_sha256("simple request"): [1.0, 0.0]}


@pytest.mark.asyncio
async def test_eval_query_embedding_cache_rejects_partial_embedding_response(
    tmp_path: Path,
):
    class PartialEmbeddingClient:
        async def embed(self, texts: list[str]) -> list[list[float]]:
            return []

    cache = EvalQueryEmbeddingCache(
        PartialEmbeddingClient(),
        tmp_path / "eval-query-embeddings.json",
        "local-embedding",
    )

    with pytest.raises(RuntimeError, match="response length"):
        await cache.embed(["simple request"])


@pytest.mark.asyncio
async def test_eval_routes_passes_configured_embedding_batch_size(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    captured: dict[str, int] = {}

    class FakeOpenAIEmbeddingClient:
        def __init__(
            self,
            url: str,
            model: str,
            timeout: float = 20.0,
            batch_size: int = 128,
            api_key: str | None = None,
            headers: dict[str, str] | None = None,
        ):
            captured["batch_size"] = batch_size

        async def embed(self, texts: list[str]) -> list[list[float]]:
            return [
                [1.0, 0.0] if "simple" in text else [0.0, 1.0]
                for text in texts
            ]

    monkeypatch.setattr(
        "scripts.eval_routes.OpenAIEmbeddingClient", FakeOpenAIEmbeddingClient
    )
    routes = tmp_path / "routes.yaml"
    routes.write_text(
        """
route_model: auto
fallback_route_id: lite
route_kernel: basic
threshold: 0.1
margin: 0.0
embedding_url: http://127.0.0.1:1234/v1/embeddings
embedding_model: local-embedding
embedding_batch_size: 7
routes:
  lite:
    target_model: cheap-router
    description: simple requests
    utterances:
      - simple request
  deep:
    target_model: pro-router
    description: hard requests
    utterances:
      - hard request
""",
        encoding="utf-8",
    )
    cases = tmp_path / "cases.yaml"
    cases.write_text(
        """
cases:
  - id: simple_001
    text: simple request
    expect: lite
""",
        encoding="utf-8",
    )

    exit_code = await run_eval(cases, routes, mock_embeddings=False)

    assert exit_code == 0
    assert captured["batch_size"] == 7
