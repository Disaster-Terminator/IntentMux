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
from router.routing import Router


@dataclass(frozen=True)
class EvalCase:
    text: str
    expect: str
    source: str = "unknown"
    id: str | None = None
    slice: str | None = None


class MockEmbeddingClient:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        if any(
            marker in text
            for marker in ("免费模型", "探活", "端点", "benchmark", "非关键样例", "测试模型")
        ):
            return [0.0, 0.0, 1.0]
        if any(
            marker in text
            for marker in ("代码", "PR", "bug", "SQL", "数据库", "查询", "方案", "靠谱", "架构", "竞态", "线上")
        ):
            return [0.0, 1.0, 0.0]
        return [1.0, 0.0, 0.0]


def load_cases(path: Path) -> list[EvalCase]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [EvalCase(**item) for item in raw["cases"]]


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
) -> int:
    settings = load_settings(routes_path)
    embedding_client = (
        MockEmbeddingClient()
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
        decision = await router.decide(
            {
                "model": settings.route_model,
                "messages": [{"role": "user", "content": case.text}],
            }
        )
        actual_route = decision.route_id or decision.target_model
        status = "PASS" if actual_route == case.expect else "FAIL"
        results.append(
            {
                "id": case_id(case, index),
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
        )
        print(
            f"{status}\t{case.expect}\t{actual_route}\t{decision.target_model}\t"
            f"{decision.reason}\t{case.text}"
        )
        if status == "FAIL":
            failures.append(case.text)

    if json_output is not None:
        json_output.write_text(
            json.dumps(
                {"schema": "intentmux-route-eval-v1", "cases": results},
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default="config/eval_cases.yaml")
    parser.add_argument("--routes", default="config/routes.yaml")
    parser.add_argument("--mock-embeddings", action="store_true")
    parser.add_argument("--json-output")
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(
            run_eval(
                cases_path=Path(args.cases),
                routes_path=Path(args.routes),
                mock_embeddings=args.mock_embeddings,
                json_output=Path(args.json_output) if args.json_output else None,
            )
        )
    )


if __name__ == "__main__":
    main()
