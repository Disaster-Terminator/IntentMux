from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from router.config import load_settings
from router.embedding import OpenAIEmbeddingClient
from router.routing import (
    Router,
    RoutingDecision,
    latest_user_text,
    looks_like_agent_instruction_boilerplate,
)


BASELINES = {
    "current-router",
    "always-lite",
    "always-deep",
    "embedding-only",
    "hard-rule-only",
}


@dataclass(frozen=True)
class EvalCase:
    text: str
    expect: str
    source: str = "unknown"
    id: str | None = None
    slice: str | None = None
    input_chars: int | None = None
    message_count: int | None = None
    context_policy: str | None = None


class MockEmbeddingClient:
    def __init__(self, known_vectors: dict[str, list[float]] | None = None):
        self.known_vectors = known_vectors or {}

    @classmethod
    def from_settings(cls, settings: Any) -> "MockEmbeddingClient":
        route_vectors = {
            "lite": [1.0, 0.0, 0.0],
            "deep": [0.0, 1.0, 0.0],
        }
        known_vectors: dict[str, list[float]] = {}
        for route_id, route in settings.routes.items():
            vector = route_vectors.get(route_id)
            if vector is None:
                continue
            for utterance in route.utterances:
                known_vectors[utterance] = vector
        return cls(known_vectors)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        known = self.known_vectors.get(text)
        if known is not None:
            return known
        if any(
            marker in text
            for marker in ("免费模型", "探活", "端点", "benchmark", "非关键样例", "测试模型")
        ):
            return [0.0, 0.0, 1.0]
        if any(
            marker in text
            for marker in (
                "代码",
                "PR",
                "bug",
                "SQL",
                "数据库",
                "查询",
                "架构",
                "竞态",
                "线上",
                "生产改动",
                "数据丢失",
                "权限绕过",
                "回滚风险",
            )
        ):
            return [0.0, 1.0, 0.0]
        return [1.0, 0.0, 0.0]


class EvalQueryEmbeddingCache:
    def __init__(self, inner: Any, cache_path: Path | None, embedding_model: str):
        self.inner = inner
        self.cache_path = cache_path
        self.embedding_model = embedding_model
        self.vectors = self._load()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        misses: list[str] = []
        seen_misses: set[str] = set()
        for text in texts:
            key = text_sha256(text)
            if key not in self.vectors and key not in seen_misses:
                misses.append(text)
                seen_misses.add(key)

        if misses:
            vectors = await self.inner.embed(misses)
            if len(vectors) != len(misses):
                raise RuntimeError("embedding response length does not match input length")
            for text, vector in zip(misses, vectors):
                self.vectors[text_sha256(text)] = vector
            self._write()

        return [self.vectors[text_sha256(text)] for text in texts]

    def _load(self) -> dict[str, list[float]]:
        if self.cache_path is None:
            return {}
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if (
            payload.get("version") != 1
            or payload.get("embedding_model") != self.embedding_model
        ):
            return {}
        items = payload.get("items")
        if not isinstance(items, dict):
            return {}
        return {
            key: vector
            for key, vector in items.items()
            if isinstance(key, str) and isinstance(vector, list)
        }

    def _write(self) -> None:
        if self.cache_path is None:
            return
        payload = {
            "version": 1,
            "embedding_model": self.embedding_model,
            "items": self.vectors,
        }
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.cache_path.with_name(f".{self.cache_path.name}.tmp")
            tmp_path.write_text(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            tmp_path.replace(self.cache_path)
        except OSError:
            return


def load_cases(path: Path) -> list[EvalCase]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    cases: list[EvalCase] = []
    for item in raw["cases"]:
        cases.append(
            EvalCase(
                text=item["text"],
                expect=item["expect"],
                source=item.get("source", "unknown"),
                id=item.get("id"),
                slice=item.get("slice"),
                input_chars=item.get("input_chars"),
                message_count=item.get("message_count"),
                context_policy=item.get("context_policy"),
            )
        )
    return cases


def validate_case_route_ids(cases: list[EvalCase], route_ids: set[str]) -> None:
    for index, case in enumerate(cases, start=1):
        if case.expect not in route_ids:
            raise ValueError(
                f"{index}: expected route_id '{case.expect}' is not configured in routes"
            )


def case_id(case: EvalCase, index: int) -> str:
    return case.id or f"case_{index:04d}"


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def run_eval(
    cases_path: Path,
    routes_path: Path,
    mock_embeddings: bool,
    json_output: Path | None = None,
    baseline: str = "current-router",
    threshold: float | None = None,
    margin: float | None = None,
    include_text: bool = False,
    stdout_limit: int = 50,
    eval_query_cache_path: Path | None = None,
) -> int:
    if baseline not in BASELINES:
        raise ValueError(f"baseline must be one of {sorted(BASELINES)}")
    settings = load_settings(routes_path)
    updates: dict[str, float] = {}
    if threshold is not None:
        updates["threshold"] = threshold
    if margin is not None:
        updates["margin"] = margin
    if updates:
        settings = settings.model_copy(update=updates)
    if mock_embeddings:
        embedding_client = MockEmbeddingClient.from_settings(settings)
    else:
        embedding_client = EvalQueryEmbeddingCache(
            OpenAIEmbeddingClient(
                settings.embedding_url,
                settings.embedding_model,
                batch_size=settings.embedding_batch_size,
                api_key=settings.embedding_api_key,
                headers=settings.embedding_headers,
            ),
            eval_query_cache_path,
            settings.embedding_model,
        )
    router = Router(settings, embedding_client)
    decision_router = router_for_baseline(router, baseline)
    failures: list[str] = []
    results: list[dict[str, Any]] = []
    suppressed_stdout_rows = 0

    cases = load_cases(cases_path)
    validate_case_route_ids(cases, set(settings.routes))

    if not mock_embeddings and baseline in {"current-router", "embedding-only"}:
        await embedding_client.embed([case.text for case in cases])

    for index, case in enumerate(cases):
        request_json = {
            "model": settings.route_model,
            "messages": [{"role": "user", "content": case.text}],
        }
        decision = await decide_for_baseline(decision_router, request_json, baseline)
        actual_route = decision.route_id or decision.target_model
        status = "PASS" if actual_route == case.expect else "FAIL"
        result = {
            "id": case_id(case, index),
            "baseline": baseline,
            "slice": case.slice,
            "text_sha256": text_sha256(case.text),
            "text_chars": len(case.text),
            "expect": case.expect,
            "actual_route": actual_route,
            "target_model": decision.target_model,
            "reason": decision.reason,
            "passed": actual_route == case.expect,
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
        for key in ("input_chars", "message_count", "context_policy"):
            value = getattr(case, key)
            if value is not None:
                result[key] = value
        if include_text:
            result["text"] = case.text
        results.append(result)
        if index < stdout_limit:
            columns = [
                status,
                case.expect,
                actual_route,
                decision.target_model,
                decision.reason or "",
                case.text if include_text else case_id(case, index),
            ]
            print("\t".join(str(column) for column in columns))
        else:
            suppressed_stdout_rows += 1
        if status == "FAIL":
            failures.append(case_id(case, index))

    if suppressed_stdout_rows:
        print(f"... suppressed {suppressed_stdout_rows} eval row(s); use --json-output for full details.")

    if json_output is not None:
        json_output.write_text(
            json.dumps(
                {
                    "schema": "intentmux-route-eval-v1",
                    "baseline": baseline,
                    "threshold": settings.threshold,
                    "margin": settings.margin,
                    "cases": results,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    if failures:
        print(f"\n{len(failures)} eval case(s) failed.")
        return 1
    print(f"\n{len(cases)} eval case(s) passed.")
    return 0


async def decide_for_baseline(router: Router, request_json: dict[str, Any], baseline: str):
    if baseline == "current-router":
        return await router.decide(request_json)
    if baseline == "embedding-only":
        return await router.decide(request_json)
    if baseline == "always-lite":
        route_id = named_route_or_fallback(router, "lite")
        return baseline_decision(router, route_id, "baseline:always-lite")
    if baseline == "always-deep":
        deep_route = "deep" if "deep" in router.settings.routes else router.settings.fallback_route_id
        return baseline_decision(router, deep_route, "baseline:always-deep")
    if baseline == "hard-rule-only":
        text = latest_user_text(request_json.get("messages", []))
        hard_rule_text = "" if looks_like_agent_instruction_boilerplate(text) else text
        hard_rule = router._matching_hard_rule(hard_rule_text)
        if hard_rule:
            route_id, keyword = hard_rule
            return baseline_decision(router, route_id, f"baseline:hard_rule:{keyword}")
        return baseline_decision(router, router.settings.fallback_route_id, "baseline:fallback")
    raise ValueError(f"unsupported baseline: {baseline}")


def router_for_baseline(router: Router, baseline: str) -> Router:
    if baseline != "embedding-only":
        return router
    settings = router.settings.model_copy(update={"hard_rules": []})
    return Router(settings, router.embedding_client)


def baseline_decision(router: Router, route_id: str, reason: str):
    return RoutingDecision(
        route_id=route_id,
        target_model=router._target_model_for_route(route_id),
        source_model=router.settings.route_model,
        reason=reason,
        policy_id=reason,
        rewrite=True,
    )


def named_route_or_fallback(router: Router, route_id: str) -> str:
    if route_id in router.settings.routes:
        return route_id
    return router.settings.fallback_route_id


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default="examples/eval_bank.sample.yaml")
    parser.add_argument("--routes", default="config/routes.yaml")
    parser.add_argument("--mock-embeddings", action="store_true")
    parser.add_argument("--json-output")
    parser.add_argument(
        "--eval-query-cache",
        help="Optional cache file for static eval query embeddings. Stores text hashes only.",
    )
    parser.add_argument("--threshold", type=float)
    parser.add_argument("--margin", type=float)
    parser.add_argument(
        "--include-text",
        action="store_true",
        help="Print eval case text to stdout. Default stdout is metadata-only.",
    )
    parser.add_argument(
        "--stdout-limit",
        type=int,
        default=50,
        help="Maximum eval rows to print to stdout. Use --json-output for full details.",
    )
    parser.add_argument(
        "--baseline",
        default="current-router",
        choices=sorted(BASELINES),
    )
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(
            run_eval(
                cases_path=Path(args.cases),
                routes_path=Path(args.routes),
                mock_embeddings=args.mock_embeddings,
                json_output=Path(args.json_output) if args.json_output else None,
                baseline=args.baseline,
                threshold=args.threshold,
                margin=args.margin,
                include_text=args.include_text,
                stdout_limit=args.stdout_limit,
                eval_query_cache_path=Path(args.eval_query_cache)
                if args.eval_query_cache
                else None,
            )
        )
    )


if __name__ == "__main__":
    main()
