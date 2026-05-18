from __future__ import annotations

import pytest

from router.config import HardRuleSpec, RouterSettings, RouteSpec, load_settings
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
        fallback_route_id="lite",
        threshold=0.5,
        margin=0.05,
        routes={
            "lite": RouteSpec(
                target_model="lite-upstream",
                description="low risk",
                utterances=["翻译成中文", "总结这篇文章"],
            ),
            "deep": RouteSpec(
                target_model="deep-upstream",
                description="high risk",
                utterances=["分析这个线上 bug", "代码审查"],
            ),
        },
        hard_rules=[{"route_id": "deep", "keywords": ["线上事故", "死锁", "密钥"]}],
    )


def canonical_settings() -> RouterSettings:
    return RouterSettings(
        route_model="auto",
        fallback_route_id="lite",
        threshold=0.5,
        margin=0.05,
        routes={
            "lite": RouteSpec(
                target_model="local-lite-model",
                description="low risk",
                utterances=["翻译成中文", "总结这篇文章"],
            ),
            "deep": RouteSpec(
                target_model="local-deep-model",
                description="high risk",
                utterances=["分析这个线上 bug", "代码审查"],
            ),
        },
        hard_rules=[{"route_id": "deep", "keywords": ["线上事故", "死锁", "密钥"]}],
    )


SUPERPOWERS_BOILERPLATE = (
    "<EXTREMELY_IMPORTANT> You have superpowers.\n\n"
    "## Instruction Priority\n"
    "Review early, review often. Dispatch a code review subagent when needed.\n"
    "<system-reminder>\n"
    "The user indicated that they do not want you to execute yet.\n"
    "</system-reminder>"
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
async def test_auto_entry_model_uses_normal_routing():
    route_settings = canonical_settings()
    vectors = {
        "翻译成中文": [1.0, 0.0, 0.0],
        "总结这篇文章": [1.0, 0.0, 0.0],
        "分析这个线上 bug": [0.0, 1.0, 0.0],
        "代码审查": [0.0, 1.0, 0.0],
        "把这句话翻译成英文": [1.0, 0.0, 0.0],
    }
    router = Router(route_settings, FakeEmbeddingClient(vectors))

    decision = await router.decide(
        {"model": "auto", "messages": [{"role": "user", "content": "把这句话翻译成英文"}]}
    )

    assert decision.route_id == "lite"
    assert decision.target_model == "local-lite-model"
    assert decision.policy_id == "embedding"


@pytest.mark.asyncio
async def test_embedding_decision_reports_matched_route_bank_provenance():
    route_settings = RouterSettings(
        route_model="auto",
        fallback_route_id="lite",
        threshold=0.5,
        margin=0.05,
        routes={
            "lite": RouteSpec(
                target_model="local-lite-model",
                description="low risk",
                utterances=["翻译成中文"],
                utterance_sources={"翻译成中文": "massive_zh_cn_general"},
            ),
            "deep": RouteSpec(
                target_model="local-deep-model",
                description="high risk",
                utterances=["分析这个线上 bug"],
                utterance_sources={"分析这个线上 bug": "swebench_issue_resolution"},
            ),
        },
    )
    vectors = {
        "翻译成中文": [1.0, 0.0, 0.0],
        "分析这个线上 bug": [0.0, 1.0, 0.0],
        "线上 bug 怎么修": [0.0, 1.0, 0.0],
    }
    router = Router(route_settings, FakeEmbeddingClient(vectors))

    decision = await router.decide(
        {"model": "auto", "messages": [{"role": "user", "content": "线上 bug 怎么修"}]}
    )

    assert decision.route_id == "deep"
    assert decision.match_source == "swebench_issue_resolution"
    assert decision.match_index == 0
    assert decision.match_text_sha256


@pytest.mark.asyncio
async def test_auto_entry_alias_works_with_legacy_route_model_config():
    route_settings = settings()
    vectors = {
        "翻译成中文": [1.0, 0.0, 0.0],
        "总结这篇文章": [1.0, 0.0, 0.0],
        "分析这个线上 bug": [0.0, 1.0, 0.0],
        "代码审查": [0.0, 1.0, 0.0],
        "把这句话翻译成英文": [1.0, 0.0, 0.0],
    }
    router = Router(route_settings, FakeEmbeddingClient(vectors))

    decision = await router.decide(
        {"model": "auto", "messages": [{"role": "user", "content": "把这句话翻译成英文"}]}
    )

    assert decision.route_id == "lite"
    assert decision.target_model == "lite-upstream"
    assert decision.policy_id == "embedding"


@pytest.mark.asyncio
async def test_legacy_semantic_router_entry_model_alias_uses_normal_routing():
    vectors = {
        "翻译成中文": [1.0, 0.0, 0.0],
        "总结这篇文章": [1.0, 0.0, 0.0],
        "分析这个线上 bug": [0.0, 1.0, 0.0],
        "代码审查": [0.0, 1.0, 0.0],
        "代码审查这个变更": [0.0, 1.0, 0.0],
    }
    router = Router(canonical_settings(), FakeEmbeddingClient(vectors))

    decision = await router.decide(
        {
            "model": "semantic-router",
            "messages": [{"role": "user", "content": "代码审查这个变更"}],
        }
    )

    assert decision.route_id == "deep"
    assert decision.target_model == "local-deep-model"
    assert decision.policy_id == "embedding"


@pytest.mark.asyncio
async def test_lite_and_deep_model_names_are_explicit_route_overrides():
    router = Router(canonical_settings(), FakeEmbeddingClient({}, fail=True))

    lite_decision = await router.decide(
        {"model": "lite", "messages": [{"role": "user", "content": "密钥疑似泄漏"}]}
    )
    deep_decision = await router.decide(
        {"model": "deep", "messages": [{"role": "user", "content": "你好"}]}
    )

    assert lite_decision.route_id == "lite"
    assert lite_decision.target_model == "local-lite-model"
    assert lite_decision.policy_id == "explicit"
    assert deep_decision.route_id == "deep"
    assert deep_decision.target_model == "local-deep-model"
    assert deep_decision.policy_id == "explicit"


@pytest.mark.asyncio
async def test_lite_and_deep_model_names_work_with_legacy_route_ids():
    router = Router(settings(), FakeEmbeddingClient({}, fail=True))

    lite_decision = await router.decide(
        {"model": "lite", "messages": [{"role": "user", "content": "密钥疑似泄漏"}]}
    )
    deep_decision = await router.decide(
        {"model": "deep", "messages": [{"role": "user", "content": "你好"}]}
    )

    assert lite_decision.route_id == "lite"
    assert lite_decision.target_model == "lite-upstream"
    assert lite_decision.policy_id == "explicit"
    assert deep_decision.route_id == "deep"
    assert deep_decision.target_model == "deep-upstream"
    assert deep_decision.policy_id == "explicit"


@pytest.mark.asyncio
async def test_metadata_route_id_accepts_canonical_ids_and_legacy_aliases():
    router = Router(canonical_settings(), FakeEmbeddingClient({}, fail=True))

    canonical_decision = await router.decide(
        {
            "model": "auto",
            "metadata": {"route_id": "deep"},
            "messages": [{"role": "user", "content": "你好"}],
        }
    )
    legacy_decision = await router.decide(
        {
            "model": "auto",
            "metadata": {"route_id": "lite"},
            "messages": [{"role": "user", "content": "密钥疑似泄漏"}],
        }
    )

    assert canonical_decision.route_id == "deep"
    assert canonical_decision.target_model == "local-deep-model"
    assert canonical_decision.policy_id == "explicit"
    assert legacy_decision.route_id == "lite"
    assert legacy_decision.target_model == "local-lite-model"
    assert legacy_decision.policy_id == "explicit"


@pytest.mark.asyncio
async def test_high_precision_hard_rule_routes_to_strong_without_embedding():
    router = Router(settings(), FakeEmbeddingClient({}))

    decision = await router.decide(
        {
            "model": "smart-router",
            "messages": [{"role": "user", "content": "生产环境发生线上事故，需要回滚"}],
        }
    )

    assert decision.route_id == "deep"
    assert decision.target_model == "deep-upstream"
    assert decision.policy_id == "hard_rule"
    assert decision.reason == "hard_rule:线上事故"
    assert decision.rewrite is True


@pytest.mark.asyncio
async def test_default_security_reviewer_role_text_does_not_force_strong_route():
    route_settings = load_settings("config/routes.yaml")
    router = Router(route_settings, FakeEmbeddingClient({}, fail=True))

    decision = await router.decide(
        {
            "model": "auto",
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "You are a security reviewer for an AI coding agent. "
                        "A terminal command was flagged by pattern matching as "
                        "potentially dangerous. Command: curl http://127.0.0.1:4000/v1/models "
                        "Assess the ACTUAL risk of this command. Respond with exactly one word."
                    ),
                }
            ],
        }
    )

    assert decision.route_id == "lite"
    assert decision.target_model == route_settings.routes["lite"].target_model
    assert decision.policy_id == "embedding_error"


@pytest.mark.asyncio
async def test_default_recursive_delete_risk_still_routes_to_deep_without_embedding():
    route_settings = load_settings("config/routes.yaml")
    router = Router(route_settings, FakeEmbeddingClient({}, fail=True))

    decision = await router.decide(
        {
            "model": "auto",
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "A terminal command was flagged by pattern matching. "
                        "Command: rm -rf \"$HOME/projects/demo/node_modules\". "
                        "Flagged reason: recursive delete. Assess the actual risk."
                    ),
                }
            ],
        }
    )

    assert decision.route_id == "deep"
    assert decision.target_model == route_settings.routes["deep"].target_model
    assert decision.policy_id == "hard_rule"
    assert decision.reason == "hard_rule:recursive delete"


@pytest.mark.asyncio
async def test_agent_instruction_boilerplate_uses_cost_first_fallback():
    route_settings = settings().model_copy(deep=True)
    route_settings.hard_rules.append(
        HardRuleSpec(route_id="deep", keywords=["code review"])
    )
    router = Router(route_settings, FakeEmbeddingClient({}, fail=True))

    decision = await router.decide(
        {
            "model": "smart-router",
            "messages": [{"role": "user", "content": SUPERPOWERS_BOILERPLATE}],
        },
        format_signals={
            "tools_present": True,
            "tool_count": 8,
            "tool_choice_present": True,
            "tool_history": True,
            "tool_call_count": 5,
            "approx_input_chars": 72_000,
            "message_count": 11,
        },
    )

    assert decision.route_id == "lite"
    assert decision.target_model == "lite-upstream"
    assert decision.policy_id == "embedding_error"
    assert decision.reason == "embedding_error"


@pytest.mark.asyncio
async def test_agent_instruction_boilerplate_does_not_trigger_hard_rule_without_signal():
    route_settings = settings().model_copy(deep=True)
    route_settings.hard_rules.append(
        HardRuleSpec(route_id="deep", keywords=["code review"])
    )
    vectors = {
        "翻译成中文": [1.0, 0.0, 0.0],
        "总结这篇文章": [1.0, 0.0, 0.0],
        "分析这个线上 bug": [0.0, 1.0, 0.0],
        "代码审查": [0.0, 1.0, 0.0],
        SUPERPOWERS_BOILERPLATE: [0.2, 0.2, 0.2],
    }
    router = Router(route_settings, FakeEmbeddingClient(vectors))

    decision = await router.decide(
        {
            "model": "smart-router",
            "messages": [{"role": "user", "content": SUPERPOWERS_BOILERPLATE}],
        },
    )

    assert decision.route_id == "lite"
    assert decision.target_model == "lite-upstream"
    assert decision.policy_id == "low_confidence"


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

    assert decision.route_id == "deep"
    assert decision.target_model == "deep-upstream"
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

    assert decision.route_id == "lite"
    assert decision.target_model == "lite-upstream"
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

    assert decision.route_id == "lite"
    assert decision.target_model == "lite-upstream"
    assert decision.policy_id == "low_confidence"
    assert decision.reason == "low_confidence"


@pytest.mark.asyncio
async def test_agent_tool_schema_does_not_override_cost_first_routing():
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

    assert decision.route_id == "lite"
    assert decision.target_model == "lite-upstream"
    assert decision.policy_id == "embedding_error"
    assert decision.reason == "embedding_error"


@pytest.mark.asyncio
async def test_agent_tool_history_does_not_override_cost_first_routing():
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

    assert decision.route_id == "lite"
    assert decision.target_model == "lite-upstream"
    assert decision.policy_id == "embedding_error"
    assert decision.reason == "embedding_error"


@pytest.mark.asyncio
async def test_legacy_functions_do_not_override_cost_first_routing():
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

    assert decision.route_id == "lite"
    assert decision.target_model == "lite-upstream"
    assert decision.policy_id == "embedding_error"
    assert decision.reason == "embedding_error"


@pytest.mark.asyncio
async def test_long_multiturn_context_does_not_override_cost_first_routing():
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

    assert decision.route_id == "lite"
    assert decision.target_model == "lite-upstream"
    assert decision.policy_id == "embedding_error"
    assert decision.reason == "embedding_error"


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

    assert decision.route_id == "lite"
    assert decision.target_model == "lite-upstream"
    assert decision.policy_id == "low_confidence"


@pytest.mark.asyncio
async def test_agent_signal_is_disabled_when_route_is_absent():
    route_settings = RouterSettings(
        route_model="smart-router",
        fallback_route_id="lite",
        threshold=0.5,
        margin=0.05,
        routes={
            "lite": RouteSpec(
                target_model="lite-upstream",
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
    assert decision.route_id == "lite"
    assert decision.target_model == "lite-upstream"
    assert decision.policy_id == "embedding_error"


@pytest.mark.asyncio
async def test_explicit_route_precedence_over_agent_signal():
    router = Router(settings(), FakeEmbeddingClient({}, fail=True))

    decision = await router.decide(
        {
            "model": "smart-router",
            "metadata": {"route_id": "lite"},
            "messages": [{"role": "user", "content": "继续"}],
        },
        format_signals={
            "tools_present": True,
            "tool_history": True,
            "approx_input_chars": 80_000,
            "message_count": 20,
        },
    )

    assert decision.route_id == "lite"
    assert decision.target_model == "lite-upstream"
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

    assert decision.route_id == "deep"
    assert decision.target_model == "deep-upstream"
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

    assert decision.route_id == "lite"
    assert decision.target_model == "lite-upstream"
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

        assert decision.target_model == "lite-upstream"
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
            "fallback": RouteSpec(target_model="lite-upstream", description="fallback", utterances=[]),
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
    assert decision.target_model == "lite-upstream"
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

    assert decision.target_model == "lite-upstream"
    assert decision.reason == "embedding_error"


@pytest.mark.asyncio
async def test_explicit_route_id_precedence_over_legacy_metadata_keys():
    router = Router(settings(), FakeEmbeddingClient({}))

    decision = await router.decide(
        {
            "model": "smart-router",
            "metadata": {
                "route_id": "deep",
                "route": "lite",
                "target_route": "legacy",
            },
            "messages": [{"role": "user", "content": "anything"}],
        }
    )

    assert decision.route_id == "deep"
    assert decision.target_model == "deep-upstream"
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

    assert decision.route_id == "deep"
    assert decision.target_model == "deep-upstream"
    assert decision.policy_id == "embedding"
