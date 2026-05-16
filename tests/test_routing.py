from __future__ import annotations

import pytest

from router.config import HardRuleSpec, RouterSettings, RouteSpec
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
        fallback_route_id="fast",
        threshold=0.5,
        margin=0.05,
        routes={
            "fast": RouteSpec(
                target_model="cheap-router",
                description="low risk",
                utterances=["翻译成中文", "总结这篇文章"],
            ),
            "strong": RouteSpec(
                target_model="pro-router",
                description="high risk",
                utterances=["分析这个线上 bug", "代码审查"],
            ),
        },
        hard_rules=[{"route_id": "strong", "keywords": ["线上事故", "死锁", "密钥"]}],
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
    assert decision.route_id is None
    assert decision.policy_id == "passthrough"
    assert decision.reason == "passthrough"
    assert decision.rewrite is False


@pytest.mark.asyncio
async def test_high_precision_hard_rule_routes_to_strong_without_embedding():
    router = Router(settings(), FakeEmbeddingClient({}))

    decision = await router.decide(
        {
            "model": "smart-router",
            "messages": [{"role": "user", "content": "生产环境发生线上事故，需要回滚"}],
        }
    )

    assert decision.route_id == "strong"
    assert decision.target_model == "pro-router"
    assert decision.policy_id == "hard_rule"
    assert decision.reason == "hard_rule:线上事故"
    assert decision.rewrite is True


@pytest.mark.asyncio
async def test_ambiguous_engineering_terms_use_embedding_not_hard_rule():
    vectors = {
        "翻译成中文": [1.0, 0.0, 0.0],
        "总结这篇文章": [1.0, 0.0, 0.0],
        "分析这个线上 bug": [0.0, 1.0, 0.0],
        "代码审查": [0.0, 1.0, 0.0],
        "帮我看这个 PR 里的索引改动是否合理": [0.0, 1.0, 0.0],
    }
    router = Router(settings(), FakeEmbeddingClient(vectors))

    decision = await router.decide(
        {
            "model": "smart-router",
            "messages": [
                {"role": "system", "content": "route normally"},
                {"role": "user", "content": "帮我看这个 PR 里的索引改动是否合理"},
            ],
        }
    )

    assert decision.route_id == "strong"
    assert decision.target_model == "pro-router"
    assert decision.policy_id == "embedding"
    assert decision.reason == "embedding"
    assert decision.score == 1.0


@pytest.mark.asyncio
async def test_ambiguous_engineering_terms_can_route_fast_when_semantics_are_light():
    vectors = {
        "翻译成中文": [1.0, 0.0, 0.0],
        "总结这篇文章": [1.0, 0.0, 0.0],
        "分析这个线上 bug": [0.0, 1.0, 0.0],
        "代码审查": [0.0, 1.0, 0.0],
        "把这个 PR 标题翻译成英文": [1.0, 0.0, 0.0],
    }
    router = Router(settings(), FakeEmbeddingClient(vectors))

    decision = await router.decide(
        {
            "model": "smart-router",
            "messages": [{"role": "user", "content": "把这个 PR 标题翻译成英文"}],
        }
    )

    assert decision.route_id == "fast"
    assert decision.target_model == "cheap-router"
    assert decision.policy_id == "embedding"
    assert decision.reason == "embedding"


@pytest.mark.asyncio
async def test_low_confidence_embedding_falls_back_to_default_route():
    vectors = {
        "翻译成中文": [1.0, 0.0, 0.0],
        "总结这篇文章": [1.0, 0.0, 0.0],
        "分析这个线上 bug": [0.0, 1.0, 0.0],
        "代码审查": [0.0, 1.0, 0.0],
        "天气怎么样": [0.2, 0.2, 0.2],
    }
    router = Router(settings(), FakeEmbeddingClient(vectors))

    decision = await router.decide(
        {
            "model": "smart-router",
            "messages": [{"role": "user", "content": "天气怎么样"}],
        }
    )

    assert decision.route_id == "fast"
    assert decision.target_model == "cheap-router"
    assert decision.policy_id == "low_confidence"
    assert decision.reason == "low_confidence"


@pytest.mark.asyncio
async def test_agent_tool_schema_routes_to_strong_before_embedding():
    router = Router(settings(), FakeEmbeddingClient({}, fail=True))

    decision = await router.decide(
        {
            "model": "smart-router",
            "messages": [{"role": "user", "content": "翻译这段工具说明"}],
        },
        format_signals={
            "tools_present": True,
            "tool_count": 12,
            "tool_choice_present": True,
            "tool_history": False,
            "approx_input_chars": 4_000,
            "message_count": 2,
        },
    )

    assert decision.route_id == "strong"
    assert decision.target_model == "pro-router"
    assert decision.policy_id == "agent_signal"
    assert decision.reason == "agent_signal:tools_present"


@pytest.mark.asyncio
async def test_agent_tool_history_routes_to_strong_before_embedding():
    router = Router(settings(), FakeEmbeddingClient({}, fail=True))

    decision = await router.decide(
        {
            "model": "smart-router",
            "messages": [{"role": "user", "content": "继续"}],
        },
        format_signals={
            "tools_present": False,
            "tool_count": 0,
            "tool_history": True,
            "tool_call_count": 3,
            "approx_input_chars": 2_000,
            "message_count": 8,
        },
    )

    assert decision.route_id == "strong"
    assert decision.target_model == "pro-router"
    assert decision.policy_id == "agent_signal"
    assert decision.reason == "agent_signal:tool_history"


@pytest.mark.asyncio
async def test_legacy_functions_route_to_strong_before_embedding():
    router = Router(settings(), FakeEmbeddingClient({}, fail=True))

    decision = await router.decide(
        {
            "model": "smart-router",
            "messages": [{"role": "user", "content": "解释这个函数"}],
        },
        format_signals={
            "functions_present": True,
            "function_count": 1,
            "tools_present": False,
            "tool_history": False,
            "approx_input_chars": 1_000,
            "message_count": 1,
        },
    )

    assert decision.route_id == "strong"
    assert decision.target_model == "pro-router"
    assert decision.policy_id == "agent_signal"
    assert decision.reason == "agent_signal:functions_present"


@pytest.mark.asyncio
async def test_long_multiturn_context_routes_to_strong_before_embedding():
    router = Router(settings(), FakeEmbeddingClient({}, fail=True))

    decision = await router.decide(
        {
            "model": "smart-router",
            "messages": [{"role": "user", "content": "总结目前状态"}],
        },
        format_signals={
            "tools_present": False,
            "tool_history": False,
            "approx_input_chars": 20_000,
            "message_count": 6,
        },
    )

    assert decision.route_id == "strong"
    assert decision.target_model == "pro-router"
    assert decision.policy_id == "agent_signal"
    assert decision.reason == "agent_signal:long_context"


@pytest.mark.asyncio
async def test_empty_agent_signal_fields_do_not_route_to_strong():
    vectors = {
        "翻译成中文": [1.0, 0.0, 0.0],
        "总结这篇文章": [1.0, 0.0, 0.0],
        "分析这个线上 bug": [0.0, 1.0, 0.0],
        "代码审查": [0.0, 1.0, 0.0],
        "天气怎么样": [0.2, 0.2, 0.2],
    }
    router = Router(settings(), FakeEmbeddingClient(vectors))

    decision = await router.decide(
        {
            "model": "smart-router",
            "messages": [{"role": "user", "content": "天气怎么样"}],
        },
        format_signals={
            "tools_present": False,
            "tool_count": 0,
            "functions_present": False,
            "function_count": 0,
            "tool_history": False,
            "tool_call_count": 0,
            "tool_choice_present": False,
            "approx_input_chars": 20_000,
            "message_count": 1,
        },
    )

    assert decision.route_id == "fast"
    assert decision.target_model == "cheap-router"
    assert decision.policy_id == "low_confidence"


@pytest.mark.asyncio
async def test_agent_signal_is_disabled_when_route_is_absent():
    route_settings = RouterSettings(
        route_model="smart-router",
        fallback_route_id="fast",
        threshold=0.5,
        margin=0.05,
        routes={
            "fast": RouteSpec(
                target_model="cheap-router",
                description="low risk",
                utterances=["翻译成中文"],
            ),
        },
    )
    router = Router(route_settings, FakeEmbeddingClient({}, fail=True))

    decision = await router.decide(
        {
            "model": "smart-router",
            "messages": [{"role": "user", "content": "翻译这段工具说明"}],
        },
        format_signals={
            "tools_present": True,
            "tool_count": 1,
            "approx_input_chars": 4_000,
            "message_count": 2,
        },
    )

    assert route_settings.effective_agent_signal_route_id is None
    assert decision.route_id == "fast"
    assert decision.target_model == "cheap-router"
    assert decision.policy_id == "embedding_error"


@pytest.mark.asyncio
async def test_explicit_route_precedence_over_agent_signal():
    router = Router(settings(), FakeEmbeddingClient({}, fail=True))

    decision = await router.decide(
        {
            "model": "smart-router",
            "metadata": {"route_id": "fast"},
            "messages": [{"role": "user", "content": "继续"}],
        },
        format_signals={
            "tools_present": True,
            "tool_history": True,
            "approx_input_chars": 80_000,
            "message_count": 20,
        },
    )

    assert decision.route_id == "fast"
    assert decision.target_model == "cheap-router"
    assert decision.policy_id == "explicit"


@pytest.mark.asyncio
async def test_hard_rule_precedence_over_agent_signal():
    router = Router(settings(), FakeEmbeddingClient({}, fail=True))

    decision = await router.decide(
        {
            "model": "smart-router",
            "messages": [{"role": "user", "content": "密钥疑似泄漏"}],
        },
        format_signals={
            "tools_present": True,
            "tool_history": True,
            "approx_input_chars": 80_000,
            "message_count": 20,
        },
    )

    assert decision.route_id == "strong"
    assert decision.target_model == "pro-router"
    assert decision.policy_id == "hard_rule"
    assert decision.reason == "hard_rule:密钥"


@pytest.mark.asyncio
async def test_embedding_failure_falls_back_to_default_route():
    router = Router(settings(), FakeEmbeddingClient({}, fail=True))

    decision = await router.decide(
        {
            "model": "smart-router",
            "messages": [{"role": "user", "content": "解释一下这个概念"}],
        }
    )

    assert decision.route_id == "fast"
    assert decision.target_model == "cheap-router"
    assert decision.policy_id == "embedding_error"
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
    assert latest_user_text(None) == ""
    assert latest_user_text("not-a-message-list") == ""
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
        "": [0.0, 0.0, 0.0],
    }
    router = Router(settings(), FakeEmbeddingClient(vectors))

    for bad_messages in (
        None,
        "not-a-message-list",
        [{"role": "user", "content": [None, {"type": "input_audio", "audio": "..."}]}],
    ):
        decision = await router.decide(
            {
                "model": "smart-router",
                "messages": bad_messages,
            }
        )

        assert decision.target_model == "cheap-router"
        assert decision.reason == "low_confidence"




@pytest.mark.asyncio
async def test_empty_utterance_route_is_skipped_for_embedding_and_hard_rule_can_still_match():
    route_settings = settings().model_copy(deep=True)
    route_settings.routes["rules-only"] = RouteSpec(
        target_model="rules-router",
        description="only hard-rule",
        utterances=[],
    )
    route_settings.hard_rules.append(HardRuleSpec(route_id="rules-only", keywords=["紧急"]))

    vectors = {
        "翻译成中文": [1.0, 0.0, 0.0],
        "总结这篇文章": [1.0, 0.0, 0.0],
        "分析这个线上 bug": [0.0, 1.0, 0.0],
        "代码审查": [0.0, 1.0, 0.0],
        "这是紧急事件": [0.1, 0.1, 0.1],
    }
    router = Router(route_settings, FakeEmbeddingClient(vectors))

    hard_rule_decision = await router.decide(
        {
            "model": "smart-router",
            "messages": [{"role": "user", "content": "这是紧急事件"}],
        }
    )

    assert hard_rule_decision.route_id == "rules-only"
    assert hard_rule_decision.policy_id == "hard_rule"
    assert hard_rule_decision.target_model == "rules-router"


@pytest.mark.asyncio
async def test_all_empty_utterance_routes_fall_back_deterministically_without_embedding_failure():
    route_settings = RouterSettings(
        route_model="smart-router",
        fallback_route_id="fallback",
        threshold=0.5,
        margin=0.05,
        routes={
            "fallback": RouteSpec(target_model="cheap-router", description="fallback", utterances=[]),
            "rules-only": RouteSpec(target_model="rules-router", description="rules", utterances=[]),
        },
    )
    router = Router(route_settings, FakeEmbeddingClient({"anything": [0.1, 0.1, 0.1]}))

    decision = await router.decide(
        {
            "model": "smart-router",
            "messages": [{"role": "user", "content": "anything"}],
        }
    )

    assert decision.route_id == "fallback"
    assert decision.target_model == "cheap-router"
    assert decision.policy_id == "low_confidence"
    assert decision.reason == "low_confidence"
    assert decision.score == 0.0
    assert decision.second_score == 0.0
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


@pytest.mark.asyncio
async def test_explicit_route_id_precedence_over_legacy_metadata_keys():
    router = Router(settings(), FakeEmbeddingClient({}))

    decision = await router.decide(
        {
            "model": "smart-router",
            "metadata": {
                "route_id": "strong",
                "route": "fast",
                "target_route": "legacy",
            },
            "messages": [{"role": "user", "content": "anything"}],
        }
    )

    assert decision.route_id == "strong"
    assert decision.target_model == "pro-router"
    assert decision.policy_id == "explicit"


@pytest.mark.asyncio
async def test_unknown_explicit_route_id_is_ignored_and_normal_routing_continues():
    vectors = {
        "翻译成中文": [1.0, 0.0, 0.0],
        "总结这篇文章": [1.0, 0.0, 0.0],
        "分析这个线上 bug": [0.0, 1.0, 0.0],
        "代码审查": [0.0, 1.0, 0.0],
        "代码审查这个变更": [0.0, 1.0, 0.0],
    }
    router = Router(settings(), FakeEmbeddingClient(vectors))

    decision = await router.decide(
        {
            "model": "smart-router",
            "metadata": {"route_id": "does-not-exist"},
            "messages": [{"role": "user", "content": "代码审查这个变更"}],
        }
    )

    assert decision.route_id == "strong"
    assert decision.target_model == "pro-router"
    assert decision.policy_id == "embedding"
