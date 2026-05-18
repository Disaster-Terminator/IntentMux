from __future__ import annotations

import argparse
import asyncio
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


BASELINES = {"current-router", "always-lite", "always-deep", "hard-rule-only"}


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


async def run_eval(
    cases_path: Path,
    routes_path: Path,
    mock_embeddings: bool,
    json_output: Path | None = None,
    baseline: str = "current-router",
) -> int:
    if baseline not in BASELINES:
        raise ValueError(f"baseline must be one of {sorted(BASELINES)}")
    settings = load_settings(routes_path)
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
    failures: list[str] = []
    results: list[dict[str, Any]] = []

    cases = load_cases(cases_path)
    validate_case_route_ids(cases, set(settings.routes))

    for index, case in enumerate(cases):
        request_json = {
            "model": settings.route_model,
            "messages": [{"role": "user", "content": case.text}],
        }
        decision = await decide_for_baseline(router, request_json, baseline)
        actual_route = decision.route_id or decision.target_model
        status = "PASS" if actual_route == case.expect else "FAIL"
        result = {
            "id": case_id(case, index),
            "baseline": baseline,
            "slice": case.slice,
            "text": case.text,
            "expect": case.expect,
            "actual_route": actual_route,
            "target_model": decision.target_model,
            "reason": decision.reason,
            "passed": actual_route == case.expect,
            "score": decision.score,
            "second_score": decision.second_score,
        }
        for key in ("input_chars", "message_count", "context_policy"):
            value = getattr(case, key)
            if value is not None:
                result[key] = value
        results.append(result)
        print(
            f"{status}\t{case.expect}\t{actual_route}\t{decision.target_model}\t"
            f"{decision.reason}\t{case.text}"
        )
        if status == "FAIL":
            failures.append(case.text)

    if json_output is not None:
        json_output.write_text(
            json.dumps(
                {
                    "schema": "intentmux-route-eval-v1",
                    "baseline": baseline,
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
            )
        )
    )


if __name__ == "__main__":
    main()
