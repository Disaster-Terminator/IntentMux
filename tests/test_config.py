from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from router.config import (
    DEFAULT_RUNTIME_HOME,
    RouteSpec,
    RouterSettings,
    default_config_path,
    load_settings,
)


def test_tracked_default_config_loads_example_route_bank(monkeypatch):
    monkeypatch.chdir(Path(__file__).resolve().parents[1])

    settings = load_settings("config/routes.yaml")

    assert settings.route_bank_path == "examples/route_bank.sample.yaml"
    assert settings.route_bank_loaded is True
    assert "翻译成中文" in settings.routes["lite"].utterances
    assert "Analyze why this bug only happens in production." in settings.routes["deep"].utterances
    assert settings.routes["lite"].utterance_sources["翻译成中文"] == "massive_zh_cn_general"
    assert (
        settings.routes["deep"].utterance_sources["Analyze why this bug only happens in production."]
        == "swebench_issue_resolution"
    )


def test_load_settings_supports_route_ids_mapped_to_target_models(tmp_path: Path):
    routes_path = tmp_path / "routes.yaml"
    routes_path.write_text(
        """
route_model: semantic-router
fallback_route_id: lite
routes:
  lite:
    target_model: local-lite-model
    description: low risk
    utterances:
      - seed lite utterance
  deep:
    target_model: local-deep-model
    description: high risk
    utterances:
      - seed deep utterance
hard_rules:
  - route_id: deep
    keywords:
      - PR
      - 线上
""",
        encoding="utf-8",
    )

    settings = load_settings(routes_path)

    assert settings.fallback_route_id == "lite"
    assert settings.routes["lite"].target_model == "local-lite-model"
    assert settings.routes["deep"].target_model == "local-deep-model"
    assert settings.hard_rules[0].route_id == "deep"
    assert settings.hard_rules[0].keywords == ["PR", "线上"]


def test_target_models_are_owned_by_routes_yaml_not_environment(
    monkeypatch, tmp_path: Path
):
    routes_path = tmp_path / "routes.yaml"
    routes_path.write_text(
        """
route_model: auto
fallback_route_id: lite
routes:
  lite:
    target_model: yaml-lite-model
    description: low risk
    utterances:
      - hi
  deep:
    target_model: yaml-deep-model
    description: high risk
    utterances:
      - fix production incident
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("ROUTER_LITE_TARGET_MODEL", "ignored-lite-model")
    monkeypatch.setenv("ROUTER_DEEP_TARGET_MODEL", "ignored-deep-model")

    settings = load_settings(routes_path)

    assert settings.routes["lite"].target_model == "yaml-lite-model"
    assert settings.routes["deep"].target_model == "yaml-deep-model"


def test_litellm_api_key_can_come_from_environment(monkeypatch, tmp_path: Path):
    routes_path = tmp_path / "routes.yaml"
    routes_path.write_text(
        """
route_model: semantic-router
fallback_route_id: lite
routes:
  lite:
    target_model: lite-upstream
    description: low risk
    utterances:
      - hi
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("ROUTER_LITELLM_API_KEY", "sk-upstream")

    settings = load_settings(routes_path)

    assert settings.litellm_api_key == "sk-upstream"


def test_inbound_api_key_can_come_from_environment(monkeypatch, tmp_path: Path):
    routes_path = tmp_path / "routes.yaml"
    routes_path.write_text(
        """
route_model: semantic-router
fallback_route_id: lite
routes:
  lite:
    target_model: lite-upstream
    description: low risk
    utterances:
      - hi
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("ROUTER_INBOUND_API_KEY", "sk-intentmux")

    settings = load_settings(routes_path)

    assert settings.inbound_api_key == "sk-intentmux"


def test_empty_litellm_api_key_env_does_not_clear_configured_key(monkeypatch, tmp_path: Path):
    routes_path = tmp_path / "routes.yaml"
    routes_path.write_text(
        """
route_model: semantic-router
fallback_route_id: lite
litellm_api_key: sk-configured
routes:
  lite:
    target_model: lite-upstream
    description: low risk
    utterances:
      - hi
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("ROUTER_LITELLM_API_KEY", "")

    settings = load_settings(routes_path)

    assert settings.litellm_api_key == "sk-configured"


def test_load_settings_merges_seed_utterances_with_route_bank(tmp_path: Path):
    routes_path = tmp_path / "routes.yaml"
    bank_path = tmp_path / "route_bank.yaml"
    routes_path.write_text(
        """
route_model: smart-router
default_route: lite-upstream
threshold: 0.55
margin: 0.04
route_bank_path: route_bank.yaml
routes:
  lite-upstream:
    description: seed cheap
    utterances:
      - seed cheap utterance
  deep-upstream:
    description: seed pro
    utterances:
      - seed pro utterance
""",
        encoding="utf-8",
    )
    bank_path.write_text(
        """
version: 1
routes:
  lite-upstream:
    utterances:
      - text: generated cheap utterance
        source: massive_zh_cn_general
      - text: seed cheap utterance
        source: duplicate
  deep-upstream:
    utterances:
      - text: generated pro utterance
        source: swebench_issue_resolution
  undeclared:
    utterances:
      - text: generated undeclared utterance
        source: old_bank
""",
        encoding="utf-8",
    )

    settings = load_settings(routes_path)

    assert settings.routes["lite-upstream"].utterances == [
        "seed cheap utterance",
        "generated cheap utterance",
    ]
    assert settings.routes["deep-upstream"].utterances == [
        "seed pro utterance",
        "generated pro utterance",
    ]
    assert "undeclared" not in settings.routes


def test_load_settings_ignores_missing_route_bank_by_default(tmp_path: Path):
    routes_path = tmp_path / "routes.yaml"
    routes_path.write_text(
        """
route_model: smart-router
default_route: lite-upstream
route_bank_path: missing.yaml
routes:
  lite-upstream:
    description: seed cheap
    utterances:
      - seed cheap utterance
""",
        encoding="utf-8",
    )

    settings = load_settings(routes_path)

    assert settings.routes["lite-upstream"].utterances == ["seed cheap utterance"]


def test_load_settings_requires_route_bank_when_enabled(tmp_path: Path):
    routes_path = tmp_path / "routes.yaml"
    routes_path.write_text(
        """
route_model: smart-router
default_route: lite-upstream
require_route_bank: true
route_bank_path: missing.yaml
routes:
  lite-upstream:
    description: seed cheap
    utterances:
      - seed cheap utterance
""",
        encoding="utf-8",
    )

    with pytest.raises(FileNotFoundError, match="required route bank not found"):
        load_settings(routes_path)


def test_load_settings_requires_route_bank_to_provide_declared_route_utterances(tmp_path: Path):
    routes_path = tmp_path / "routes.yaml"
    bank_path = tmp_path / "route_bank.yaml"
    routes_path.write_text(
        """
route_model: smart-router
default_route: lite-upstream
require_route_bank: true
route_bank_path: route_bank.yaml
routes:
  lite-upstream:
    description: seed cheap
    utterances:
      - seed cheap utterance
""",
        encoding="utf-8",
    )
    bank_path.write_text(
        """
version: 1
routes:
  unknown:
    utterances:
      - text: generated unknown utterance
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="required route bank did not provide utterances"):
        load_settings(routes_path)


def test_load_settings_required_route_bank_accepts_duplicate_utterances(tmp_path: Path):
    routes_path = tmp_path / "routes.yaml"
    bank_path = tmp_path / "route_bank.yaml"
    routes_path.write_text(
        """
route_model: smart-router
default_route: lite-upstream
require_route_bank: true
route_bank_path: route_bank.yaml
routes:
  lite-upstream:
    description: seed cheap
    utterances:
      - seed cheap utterance
""",
        encoding="utf-8",
    )
    bank_path.write_text(
        """
version: 1
routes:
  lite-upstream:
    utterances:
      - text: seed cheap utterance
        source: duplicate
""",
        encoding="utf-8",
    )

    settings = load_settings(routes_path)

    assert settings.route_bank_loaded is True
    assert settings.routes["lite-upstream"].utterances == ["seed cheap utterance"]


def test_load_settings_requires_route_bank_via_environment(monkeypatch, tmp_path: Path):
    routes_path = tmp_path / "routes.yaml"
    routes_path.write_text(
        """
route_model: smart-router
default_route: lite-upstream
route_bank_path: missing.yaml
routes:
  lite-upstream:
    description: seed cheap
    utterances:
      - seed cheap utterance
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("ROUTER_REQUIRE_ROUTE_BANK", "true")

    with pytest.raises(FileNotFoundError, match="required route bank not found"):
        load_settings(routes_path)


def test_load_settings_resolves_route_bank_from_cwd_when_not_next_to_config(
    tmp_path: Path,
    monkeypatch,
):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    data_dir = tmp_path / "data" / "semantic_sets"
    data_dir.mkdir(parents=True)
    routes_path = config_dir / "routes.yaml"
    routes_path.write_text(
        """
route_model: smart-router
default_route: lite-upstream
route_bank_path: data/semantic_sets/route_bank.yaml
routes:
  lite-upstream:
    description: seed cheap
    utterances:
      - seed cheap utterance
""",
        encoding="utf-8",
    )
    (data_dir / "route_bank.yaml").write_text(
        """
version: 1
routes:
  lite-upstream:
    utterances:
      - text: generated cheap utterance
        source: cwd_bank
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    settings = load_settings(routes_path)

    assert settings.routes["lite-upstream"].utterances == [
        "seed cheap utterance",
        "generated cheap utterance",
    ]
    assert settings.route_bank_loaded is True


def test_embedding_api_key_and_headers_can_come_from_environment(
    monkeypatch, tmp_path: Path
):
    routes_path = tmp_path / "routes.yaml"
    routes_path.write_text(
        """
route_model: semantic-router
default_route: lite-upstream
routes:
  lite-upstream:
    description: seed cheap
    utterances:
      - seed cheap utterance
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("ROUTER_EMBEDDING_API_KEY", "sk-embed")
    monkeypatch.setenv("ROUTER_EMBEDDING_HEADERS_JSON", '{"X-Provider": "local"}')

    settings = load_settings(routes_path)

    assert settings.embedding_api_key == "sk-embed"
    assert settings.embedding_headers == {"X-Provider": "local"}


def test_route_embedding_cache_defaults_to_runtime_home(monkeypatch, tmp_path: Path):
    runtime_home = tmp_path / "intentmux-home"
    routes_path = runtime_home / "config" / "routes.yaml"
    routes_path.parent.mkdir(parents=True)
    routes_path.write_text(
        """
route_model: semantic-router
default_route: lite-upstream
routes:
  lite-upstream:
    description: seed cheap
    utterances:
      - seed cheap utterance
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("INTENTMUX_HOME", str(runtime_home))

    settings = load_settings(routes_path)

    assert settings.route_embedding_cache_enabled is True
    assert settings.route_embedding_cache_path == str(
        runtime_home / "cache" / "route-embeddings.json"
    )


def test_route_embedding_cache_path_can_come_from_environment(
    monkeypatch, tmp_path: Path
):
    routes_path = tmp_path / "routes.yaml"
    routes_path.write_text(
        """
route_model: semantic-router
default_route: lite-upstream
routes:
  lite-upstream:
    description: seed cheap
    utterances:
      - seed cheap utterance
""",
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "ROUTER_ROUTE_EMBEDDING_CACHE_PATH", str(tmp_path / "custom-cache.json")
    )
    monkeypatch.setenv("ROUTER_ROUTE_EMBEDDING_CACHE_ENABLED", "false")

    settings = load_settings(routes_path)

    assert settings.route_embedding_cache_enabled is False
    assert settings.route_embedding_cache_path == str(tmp_path / "custom-cache.json")


def test_empty_embedding_api_key_env_does_not_clear_configured_key(
    monkeypatch, tmp_path: Path
):
    routes_path = tmp_path / "routes.yaml"
    routes_path.write_text(
        """
route_model: semantic-router
default_route: lite-upstream
embedding_api_key: sk-configured
routes:
  lite-upstream:
    description: seed cheap
    utterances:
      - seed cheap utterance
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("ROUTER_EMBEDDING_API_KEY", "")

    settings = load_settings(routes_path)

    assert settings.embedding_api_key == "sk-configured"


def test_invalid_embedding_headers_json_env_fails_loudly(monkeypatch, tmp_path: Path):
    routes_path = tmp_path / "routes.yaml"
    routes_path.write_text(
        """
route_model: semantic-router
default_route: lite-upstream
routes:
  lite-upstream:
    description: seed cheap
    utterances:
      - seed cheap utterance
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("ROUTER_EMBEDDING_HEADERS_JSON", "not-json")

    with pytest.raises(ValueError, match="ROUTER_EMBEDDING_HEADERS_JSON"):
        load_settings(routes_path)


def test_default_hard_rules_keep_only_high_precision_deep_escalations():
    settings = load_settings("config/routes.yaml")

    keywords = [keyword for hard_rule in settings.hard_rules for keyword in hard_rule.keywords]
    assert "生产" not in keywords
    assert "线上" not in keywords
    assert "PR" not in keywords
    assert "部署" not in keywords
    assert "索引" not in keywords
    assert "异常" not in keywords
    assert "报错" not in keywords
    assert "token" not in keywords
    assert "安全" not in keywords
    assert "security reviewer" not in keywords
    assert "coding agent" not in keywords
    assert "线上事故" in keywords
    assert "密钥" in keywords
    assert "bearer token" in keywords
    assert "recursive delete" in keywords
    assert "安全漏洞" in keywords
    assert settings.hard_rules[0].route_id == "deep"


def test_router_settings_defaults_entry_model_to_semantic_router():
    settings = RouterSettings(
        routes={
            "lite": RouteSpec(description="low risk", utterances=["x"]),
        }
    )
    assert settings.route_model == "semantic-router"
    assert settings.entry_model == "semantic-router"


def test_router_settings_accepts_legacy_route_model_config_key():
    settings = RouterSettings.model_validate(
        {
            "route_model": "smart-router",
            "routes": {"lite": {"description": "low risk", "utterances": ["x"]}},
        }
    )
    assert settings.route_model == "smart-router"


def test_load_settings_reads_litellm_timeout_override(tmp_path: Path, monkeypatch):
    routes_path = tmp_path / "routes.yaml"
    routes_path.write_text(
        """
route_model: semantic-router
default_route: lite-upstream
routes:
  lite-upstream:
    description: seed cheap
    utterances:
      - seed cheap utterance
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("ROUTER_LITELLM_TIMEOUT", "123.5")

    settings = load_settings(routes_path)

    assert settings.litellm_timeout == 123.5


def test_load_settings_uses_router_config_env_when_path_not_supplied(
    tmp_path: Path, monkeypatch
):
    routes_path = tmp_path / "runtime" / "config" / "routes.yaml"
    routes_path.parent.mkdir(parents=True)
    routes_path.write_text(
        """
route_model: runtime-router
fallback_route_id: runtime-lite
routes:
  runtime-lite:
    target_model: runtime-target
    description: runtime config
    utterances:
      - runtime utterance
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("ROUTER_CONFIG", str(routes_path))

    settings = load_settings()

    assert settings.route_model == "runtime-router"
    assert settings.routes["runtime-lite"].target_model == "runtime-target"


def test_default_config_path_uses_intentmux_home_when_router_config_is_unset(
    tmp_path: Path, monkeypatch
):
    runtime_home = tmp_path / "intentmux-home"
    monkeypatch.delenv("ROUTER_CONFIG", raising=False)
    monkeypatch.setenv("INTENTMUX_HOME", str(runtime_home))

    assert default_config_path() == runtime_home / "config" / "routes.yaml"


def test_default_config_path_uses_ignored_repo_runtime_home_when_present(
    tmp_path: Path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    routes_path = DEFAULT_RUNTIME_HOME / "config" / "routes.yaml"
    routes_path.parent.mkdir(parents=True)
    routes_path.write_text("routes: {}\n", encoding="utf-8")
    monkeypatch.delenv("ROUTER_CONFIG", raising=False)
    monkeypatch.delenv("INTENTMUX_HOME", raising=False)

    assert default_config_path() == routes_path


def test_default_config_path_falls_back_to_repo_config_for_source_checkout(
    tmp_path: Path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ROUTER_CONFIG", raising=False)
    monkeypatch.delenv("INTENTMUX_HOME", raising=False)

    assert default_config_path() == Path("config/routes.yaml")


def test_router_config_env_takes_precedence_over_intentmux_home(
    tmp_path: Path, monkeypatch
):
    runtime_home = tmp_path / "intentmux-home"
    explicit_config = tmp_path / "custom" / "routes.yaml"
    monkeypatch.setenv("INTENTMUX_HOME", str(runtime_home))
    monkeypatch.setenv("ROUTER_CONFIG", str(explicit_config))

    assert default_config_path() == explicit_config


def test_load_settings_uses_intentmux_home_defaults_for_runtime_paths(
    tmp_path: Path, monkeypatch
):
    runtime_home = tmp_path / "intentmux-home"
    routes_path = runtime_home / "config" / "routes.yaml"
    routes_path.parent.mkdir(parents=True)
    routes_path.write_text(
        """
route_model: auto
fallback_route_id: lite
audit_log_enabled: true
routes:
  lite:
    target_model: lite-upstream
    description: low risk
    utterances:
      - hi
""",
        encoding="utf-8",
    )
    monkeypatch.delenv("ROUTER_CONFIG", raising=False)
    monkeypatch.delenv("ROUTER_AUDIT_LOG_DIR", raising=False)
    monkeypatch.delenv("ROUTER_PROMPT_LOG_DIR", raising=False)
    monkeypatch.setenv("INTENTMUX_HOME", str(runtime_home))
    monkeypatch.setenv("ROUTER_PROMPT_LOG_MODE", "raw_local")

    settings = load_settings()

    assert settings.route_model == "auto"
    assert settings.audit_log_dir == str(runtime_home / "logs" / "routes")
    assert settings.prompt_log_mode == "raw_local"
    assert settings.prompt_log_dir == str(runtime_home / "logs" / "prompts")


def test_load_settings_defaults_logs_to_ignored_repo_runtime_home(
    tmp_path: Path, monkeypatch
):
    routes_path = tmp_path / "routes.yaml"
    routes_path.write_text(
        """
route_model: auto
fallback_route_id: lite
audit_log_enabled: true
routes:
  lite:
    target_model: lite-upstream
    description: low risk
    utterances:
      - hi
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("INTENTMUX_HOME", raising=False)
    monkeypatch.delenv("ROUTER_AUDIT_LOG_DIR", raising=False)
    monkeypatch.delenv("ROUTER_PROMPT_LOG_DIR", raising=False)
    monkeypatch.setenv("ROUTER_PROMPT_LOG_MODE", "raw_local")

    settings = load_settings(routes_path)

    assert settings.audit_log_dir == str(DEFAULT_RUNTIME_HOME / "logs" / "routes")
    assert settings.prompt_log_dir == str(DEFAULT_RUNTIME_HOME / "logs" / "prompts")


def test_load_settings_fails_loudly_when_router_config_env_is_missing(
    tmp_path: Path, monkeypatch
):
    missing_path = tmp_path / "missing" / "routes.yaml"
    monkeypatch.setenv("ROUTER_CONFIG", str(missing_path))

    with pytest.raises(FileNotFoundError, match=str(missing_path)):
        load_settings()


def test_load_settings_reads_audit_log_overrides(tmp_path: Path, monkeypatch):
    routes_path = tmp_path / "routes.yaml"
    audit_dir = tmp_path / "logs" / "routes"
    routes_path.write_text(
        """
route_model: semantic-router
default_route: lite-upstream
routes:
  lite-upstream:
    description: seed cheap
    utterances:
      - seed cheap utterance
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("ROUTER_AUDIT_LOG_DIR", str(audit_dir))
    monkeypatch.setenv("ROUTER_AUDIT_LOG_ENABLED", "true")
    monkeypatch.setenv("ROUTER_AUDIT_LOG_TIMEZONE", "UTC")

    settings = load_settings(routes_path)

    assert settings.audit_log_dir == str(audit_dir)
    assert settings.audit_log_enabled is True
    assert settings.audit_log_timezone == "UTC"


def test_load_settings_reads_prompt_review_log_overrides(tmp_path: Path, monkeypatch):
    routes_path = tmp_path / "routes.yaml"
    prompt_dir = tmp_path / "logs" / "prompts"
    routes_path.write_text(
        """
route_model: semantic-router
default_route: lite-upstream
routes:
  lite-upstream:
    description: seed cheap
    utterances:
      - seed cheap utterance
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("ROUTER_PROMPT_LOG_MODE", "raw_local")
    monkeypatch.setenv("ROUTER_PROMPT_LOG_DIR", str(prompt_dir))
    monkeypatch.setenv("ROUTER_PROMPT_LOG_MAX_CHARS", "123")

    settings = load_settings(routes_path)

    assert settings.prompt_log_mode == "raw_local"
    assert settings.prompt_log_dir == str(prompt_dir)
    assert settings.prompt_log_max_chars == 123


def test_load_settings_defaults_prompt_review_log_dir_for_runtime_home(
    tmp_path: Path, monkeypatch
):
    routes_path = tmp_path / "routes.yaml"
    routes_path.write_text(
        """
route_model: semantic-router
default_route: lite-upstream
routes:
  lite-upstream:
    description: seed cheap
    utterances:
      - seed cheap utterance
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("INTENTMUX_HOME", raising=False)
    monkeypatch.delenv("ROUTER_PROMPT_LOG_DIR", raising=False)
    monkeypatch.setenv("ROUTER_PROMPT_LOG_MODE", "raw_local")

    settings = load_settings(routes_path)

    assert settings.prompt_log_dir == str(DEFAULT_RUNTIME_HOME / "logs" / "prompts")


def test_router_settings_rejects_prompt_review_log_without_directory():
    with pytest.raises(ValidationError, match="prompt_log_dir"):
        RouterSettings(
            route_model="semantic-router",
            fallback_route_id="lite",
            prompt_log_mode="raw_local",
            routes={
                "lite": RouteSpec(
                    target_model="lite-upstream",
                    description="seed cheap",
                    utterances=["seed cheap utterance"],
                )
            },
        )


def test_load_settings_disables_access_log_by_default(tmp_path: Path):
    routes_path = tmp_path / "routes.yaml"
    routes_path.write_text(
        """
route_model: semantic-router
default_route: lite-upstream
routes:
  lite-upstream:
    description: seed cheap
    utterances:
      - seed cheap utterance
""",
        encoding="utf-8",
    )

    settings = load_settings(routes_path)

    assert settings.access_log is False


def test_load_settings_reads_access_log_override(tmp_path: Path, monkeypatch):
    routes_path = tmp_path / "routes.yaml"
    routes_path.write_text(
        """
route_model: semantic-router
default_route: lite-upstream
routes:
  lite-upstream:
    description: seed cheap
    utterances:
      - seed cheap utterance
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("ROUTER_ACCESS_LOG", "true")

    settings = load_settings(routes_path)

    assert settings.access_log is True


def test_load_settings_reads_readiness_timeout_override(tmp_path: Path, monkeypatch):
    routes_path = tmp_path / "routes.yaml"
    routes_path.write_text(
        """
route_model: semantic-router
default_route: lite-upstream
routes:
  lite-upstream:
    description: seed cheap
    utterances:
      - seed cheap utterance
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("ROUTER_READINESS_TIMEOUT", "0.25")

    settings = load_settings(routes_path)

    assert settings.readiness_timeout == 0.25


def test_router_settings_rejects_default_route_that_points_back_to_entry_model():
    with pytest.raises(ValidationError, match="fallback_route_id"):
        RouterSettings(
            route_model="semantic-router",
            default_route="semantic-router",
            routes={
                "lite-upstream": RouteSpec(
                    description="seed cheap",
                    utterances=["seed cheap utterance"],
                )
            },
        )


def test_router_settings_rejects_recursive_route_target():
    with pytest.raises(ValidationError, match="recursive"):
        RouterSettings(
            route_model="semantic-router",
            default_route="lite-upstream",
            routes={
                "semantic-router": RouteSpec(
                    description="recursive target",
                    utterances=["send back to entry model"],
                ),
                "lite-upstream": RouteSpec(
                    description="seed cheap",
                    utterances=["seed cheap utterance"],
                ),
            },
        )


def test_router_settings_allows_user_defined_route_ids_and_target_models():
    settings = RouterSettings(
        route_model="semantic-router",
        fallback_route_id="local",
        routes={
            "local": RouteSpec(
                target_model="my-local-litellm-group",
                description="local lite target",
                utterances=["quick local prompt"],
            ),
            "premium": RouteSpec(
                target_model="my-premium-litellm-group",
                description="premium target",
                utterances=["hard analysis prompt"],
            ),
        },
    )

    assert set(settings.routes) == {"local", "premium"}
    assert settings.routes["local"].target_model == "my-local-litellm-group"


def test_router_settings_rejects_recursive_target_model():
    with pytest.raises(ValidationError, match="target_model"):
        RouterSettings(
            route_model="semantic-router",
            fallback_route_id="lite",
            routes={
                "lite": RouteSpec(
                    target_model="semantic-router",
                    description="recursive target",
                    utterances=["send back to entry model"],
                ),
            },
        )


def test_router_settings_accepts_entry_model_alias_key():
    settings = RouterSettings.model_validate(
        {
            "entry_model": "smart-router",
            "routes": {"lite": {"description": "low risk", "utterances": ["x"]}},
        }
    )
    assert settings.route_model == "smart-router"
    assert settings.entry_model == "smart-router"


def test_router_settings_prefers_route_model_when_both_alias_keys_present():
    settings = RouterSettings.model_validate(
        {
            "route_model": "route-model-wins",
            "entry_model": "entry-model-loses",
            "routes": {"lite": {"description": "low risk", "utterances": ["x"]}},
        }
    )

    assert settings.route_model == "route-model-wins"


def test_router_settings_accepts_fallback_route_id_key():
    settings = RouterSettings.model_validate(
        {
            "fallback_route_id": "lite",
            "routes": {"lite": {"description": "low risk", "utterances": ["x"]}},
        }
    )

    assert settings.fallback_route_id == "lite"
    assert settings.default_route == "lite"


def test_router_settings_accepts_default_route_legacy_alias_key():
    settings = RouterSettings.model_validate(
        {
            "default_route": "lite",
            "routes": {"lite": {"description": "low risk", "utterances": ["x"]}},
        }
    )

    assert settings.fallback_route_id == "lite"


def test_router_settings_defaults_target_model_to_route_id_when_omitted():
    settings = RouterSettings.model_validate(
        {
            "routes": {
                "lite": {"description": "low risk", "utterances": ["x"]},
                "deep": {"description": "high risk", "utterances": ["y"]},
            }
        }
    )

    assert settings.routes["lite"].target_model == "lite"
    assert settings.routes["deep"].target_model == "deep"


def test_router_settings_defaults_agent_signal_to_strong_when_present():
    settings = RouterSettings.model_validate(
        {
            "routes": {
                "lite": {"description": "low risk", "utterances": ["x"]},
                "deep": {"description": "high risk", "utterances": ["y"]},
            }
        }
    )

    assert settings.agent_signal_route_id is None
    assert settings.effective_agent_signal_route_id == "deep"


def test_router_settings_defaults_agent_signal_to_deep_when_present():
    settings = RouterSettings.model_validate(
        {
            "fallback_route_id": "lite",
            "routes": {
                "lite": {"description": "low risk", "utterances": ["x"]},
                "deep": {"description": "high risk", "utterances": ["y"]},
            },
        }
    )

    assert settings.agent_signal_route_id is None
    assert settings.effective_agent_signal_route_id == "deep"


def test_router_settings_accepts_legacy_route_aliases_with_canonical_routes():
    settings = RouterSettings.model_validate(
        {
            "fallback_route_id": "lite",
            "agent_signal_route_id": "deep",
            "routes": {
                "lite": {"description": "low risk", "utterances": ["x"]},
                "deep": {"description": "high risk", "utterances": ["y"]},
            },
            "hard_rules": [{"route_id": "deep", "keywords": ["prod"]}],
        }
    )

    assert settings.fallback_route_id == "lite"
    assert settings.agent_signal_route_id == "deep"
    assert settings.hard_rules[0].route_id == "deep"


def test_router_settings_accepts_canonical_route_aliases_with_legacy_routes():
    settings = RouterSettings.model_validate(
        {
            "fallback_route_id": "lite",
            "agent_signal_route_id": "deep",
            "routes": {
                "lite": {"description": "low risk", "utterances": ["x"]},
                "deep": {"description": "high risk", "utterances": ["y"]},
            },
            "hard_rules": [{"route_id": "deep", "keywords": ["prod"]}],
        }
    )

    assert settings.fallback_route_id == "lite"
    assert settings.agent_signal_route_id == "deep"
    assert settings.hard_rules[0].route_id == "deep"


def test_router_settings_disables_agent_signal_when_strong_is_absent_by_default():
    settings = RouterSettings.model_validate(
        {
            "routes": {
                "lite": {"description": "low risk", "utterances": ["x"]},
            }
        }
    )

    assert settings.agent_signal_route_id is None
    assert settings.effective_agent_signal_route_id is None


def test_router_settings_rejects_unknown_explicit_agent_signal_route_id():
    with pytest.raises(ValidationError, match="agent_signal_route_id"):
        RouterSettings.model_validate(
            {
                "agent_signal_route_id": "missing",
                "routes": {
                    "lite": {"description": "low risk", "utterances": ["x"]},
                },
            }
        )


def test_router_settings_rejects_missing_fallback_route_id_in_routes():
    with pytest.raises(ValidationError, match="fallback_route_id must be present"):
        RouterSettings.model_validate(
            {
                "fallback_route_id": "missing",
                "routes": {
                    "lite": {"description": "low risk", "utterances": ["x"]},
                },
            }
        )
