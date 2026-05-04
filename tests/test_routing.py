from __future__ import annotations

import pytest

from router.config import RouterSettings, RouteSpec
from router.routing import Router, latest_user_text


class FakeEmbeddingClient:
    def __init__(self, vectors: dict[str, list[float]], fail: bool = False):
        self.vectors = vectors
        self.fail = fail

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if self.fail:
            raise RuntimeError("embedding unavailable")
        return [self.vectors[text] for text in texts]


def settings() -> RouterSettings:
    return RouterSettings(
        route_model="smart-router",
        default_route="cheap-router",
        threshold=0.5,
        margin=0.05,
        routes={
            "cheap-router": RouteSpec(
                description="low risk",
                utterances=["翻译成中文", "总结这篇文章"],
            ),
            "pro-router": RouteSpec(
                description="high risk",
                utterances=["分析这个线上 bug", "代码审查"],
            ),
            "free-probe-router": RouteSpec(
                description="probe",
                utterances=["测试免费模型", "批量探活"],
            ),
        },
        pro_hard_rules=["报错", "竞态", "线上", "PR"],
    )


@pytest.mark.asyncio
async def test_non_smart_router_passes_through_without_embedding():
    router = Router(settings(), FakeEmbeddingClient({}))

    decision = await router.decide(
        {
            "model": "deepseek-v4-pro",
            "messages": [{"role": "user", "content": "帮我分析这个 PR"}],
        }
    )

    assert decision.target_model == "deepseek-v4-pro"
    assert decision.reason == "passthrough"
    assert decision.rewrite is False


@pytest.mark.asyncio
async def test_hard_rule_routes_smart_router_to_pro_without_embedding():
    router = Router(settings(), FakeEmbeddingClient({}))

    decision = await router.decide(
        {
            "model": "smart-router",
            "messages": [{"role": "user", "content": "这个 NPE 为什么只在线上偶发"}],
        }
    )

    assert decision.target_model == "pro-router"
    assert decision.reason == "hard_rule:线上"
    assert decision.rewrite is True


@pytest.mark.asyncio
async def test_embedding_similarity_routes_probe_request():
    vectors = {
        "翻译成中文": [1.0, 0.0, 0.0],
        "总结这篇文章": [1.0, 0.0, 0.0],
        "分析这个线上 bug": [0.0, 1.0, 0.0],
        "代码审查": [0.0, 1.0, 0.0],
        "测试免费模型": [0.0, 0.0, 1.0],
        "批量探活": [0.0, 0.0, 1.0],
        "批量测试这些免费模型哪个还活着": [0.0, 0.0, 1.0],
    }
    router = Router(settings(), FakeEmbeddingClient(vectors))

    decision = await router.decide(
        {
            "model": "smart-router",
            "messages": [
                {"role": "system", "content": "route normally"},
                {"role": "user", "content": "批量测试这些免费模型哪个还活着"},
            ],
        }
    )

    assert decision.target_model == "free-probe-router"
    assert decision.reason == "embedding"
    assert decision.score == 1.0


@pytest.mark.asyncio
async def test_low_confidence_embedding_falls_back_to_default_route():
    vectors = {
        "翻译成中文": [1.0, 0.0, 0.0],
        "总结这篇文章": [1.0, 0.0, 0.0],
        "分析这个线上 bug": [0.0, 1.0, 0.0],
        "代码审查": [0.0, 1.0, 0.0],
        "测试免费模型": [0.0, 0.0, 1.0],
        "批量探活": [0.0, 0.0, 1.0],
        "天气怎么样": [0.2, 0.2, 0.2],
    }
    router = Router(settings(), FakeEmbeddingClient(vectors))

    decision = await router.decide(
        {
            "model": "smart-router",
            "messages": [{"role": "user", "content": "天气怎么样"}],
        }
    )

    assert decision.target_model == "cheap-router"
    assert decision.reason == "low_confidence"


@pytest.mark.asyncio
async def test_embedding_failure_falls_back_to_default_route():
    router = Router(settings(), FakeEmbeddingClient({}, fail=True))

    decision = await router.decide(
        {
            "model": "smart-router",
            "messages": [{"role": "user", "content": "解释一下这个概念"}],
        }
    )

    assert decision.target_model == "cheap-router"
    assert decision.reason == "embedding_error"



def test_latest_user_text_uses_latest_user_message_not_older_ones():
    messages = [
        {"role": "user", "content": "older"},
        {"role": "assistant", "content": "ignored"},
        {"role": "user", "content": "latest"},
    ]

    assert latest_user_text(messages) == "latest"


def test_latest_user_text_joins_multiple_text_parts_and_ignores_non_text_parts():
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "input_audio", "audio": "..."},
                {"type": "text", "text": "line 1"},
                {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}},
                {"type": "text", "text": "line 2"},
            ],
        }
    ]

    assert latest_user_text(messages) == "line 1\nline 2"


def test_latest_user_text_returns_empty_string_for_missing_none_or_invalid_content():
    assert latest_user_text([]) == ""
    assert latest_user_text([{"role": "assistant", "content": "x"}]) == ""
    assert latest_user_text([{"role": "user"}]) == ""
    assert latest_user_text([{"role": "user", "content": None}]) == ""
    assert latest_user_text([{"role": "user", "content": [None, "bad", {"type": "text"}]}]) == ""


def test_latest_user_text_latest_invalid_user_message_wins_and_returns_empty():
    messages = [
        {"role": "user", "content": "older useful"},
        {"role": "user", "content": None},
    ]

    assert latest_user_text(messages) == ""


@pytest.mark.asyncio
async def test_decide_with_empty_extracted_text_returns_low_confidence_not_crash():
    vectors = {
        "翻译成中文": [1.0, 0.0, 0.0],
        "总结这篇文章": [1.0, 0.0, 0.0],
        "分析这个线上 bug": [0.0, 1.0, 0.0],
        "代码审查": [0.0, 1.0, 0.0],
        "测试免费模型": [0.0, 0.0, 1.0],
        "批量探活": [0.0, 0.0, 1.0],
        "": [0.0, 0.0, 0.0],
    }
    router = Router(settings(), FakeEmbeddingClient(vectors))

    decision = await router.decide(
        {
            "model": "smart-router",
            "messages": [{"role": "user", "content": [None, {"type": "input_audio", "audio": "..."}]}],
        }
    )

    assert decision.target_model == "cheap-router"
    assert decision.reason == "low_confidence"


@pytest.mark.asyncio
async def test_decide_with_empty_messages_and_embedding_failure_returns_embedding_error():
    router = Router(settings(), FakeEmbeddingClient({}, fail=True))

    decision = await router.decide(
        {
            "model": "smart-router",
            "messages": [],
        }
    )

    assert decision.target_model == "cheap-router"
    assert decision.reason == "embedding_error"
