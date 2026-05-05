from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

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


def validate_case_routes(cases: list[EvalCase], valid_route_ids: set[str]) -> None:
    invalid = sorted({case.expect for case in cases if case.expect not in valid_route_ids})
    if invalid:
        invalid_text = ", ".join(invalid)
        raise ValueError(f"eval case expect route_id not in routes config: {invalid_text}")


async def run_eval(
    cases_path: Path,
    routes_path: Path,
    mock_embeddings: bool,
) -> int:
    settings = load_settings(routes_path)
    embedding_client = (
        MockEmbeddingClient()
        if mock_embeddings
        else OpenAIEmbeddingClient(settings.embedding_url, settings.embedding_model)
    )
    router = Router(settings, embedding_client)
    cases = load_cases(cases_path)
    validate_case_routes(cases, set(settings.routes.keys()))
    failures: list[str] = []

    for case in cases:
        decision = await router.decide(
            {
                "model": settings.route_model,
                "messages": [{"role": "user", "content": case.text}],
            }
        )
        actual_route = decision.route_id or decision.target_model
        status = "PASS" if actual_route == case.expect else "FAIL"
        print(
            f"{status}\t{case.expect}\t{actual_route}\t{decision.target_model}\t"
            f"{decision.reason}\t{case.text}"
        )
        if status == "FAIL":
            failures.append(case.text)

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
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(
            run_eval(
                cases_path=Path(args.cases),
                routes_path=Path(args.routes),
                mock_embeddings=args.mock_embeddings,
            )
        )
    )


if __name__ == "__main__":
    main()
