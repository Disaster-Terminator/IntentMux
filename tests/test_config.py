from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from router.config import RouteSpec, RouterSettings, load_settings


def test_load_settings_supports_route_ids_mapped_to_target_models(tmp_path: Path):
    routes_path = tmp_path / "routes.yaml"
    routes_path.write_text(
        """
route_model: semantic-router
fallback_route_id: fast
routes:
  fast:
    target_model: local-fast-model
    description: low risk
    utterances:
      - seed fast utterance
  strong:
    target_model: local-strong-model
    description: high risk
    utterances:
      - seed strong utterance
hard_rules:
  - route_id: strong
    keywords:
      - PR
      - 线上
""",
        encoding="utf-8",
    )

    settings = load_settings(routes_path)

    assert settings.fallback_route_id == "fast"
    assert settings.routes["fast"].target_model == "local-fast-model"
    assert settings.routes["strong"].target_model == "local-strong-model"
    assert settings.hard_rules[0].route_id == "strong"
    assert settings.hard_rules[0].keywords == ["PR", "线上"]


def test_litellm_api_key_can_come_from_environment(monkeypatch, tmp_path: Path):
    routes_path = tmp_path / "routes.yaml"
    routes_path.write_text(
        """
route_model: semantic-router
fallback_route_id: fast
routes:
  fast:
    target_model: cheap-router
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
fallback_route_id: fast
routes:
  fast:
    target_model: cheap-router
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
fallback_route_id: fast
litellm_api_key: sk-configured
routes:
  fast:
    target_model: cheap-router
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
default_route: cheap-router
threshold: 0.55
margin: 0.04
route_bank_path: route_bank.yaml
routes:
  cheap-router:
    description: seed cheap
    utterances:
      - seed cheap utterance
  pro-router:
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
  cheap-router:
    utterances:
      - text: generated cheap utterance
        source: massive_zh_cn_general
      - text: seed cheap utterance
        source: duplicate
  pro-router:
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

    assert settings.routes["cheap-router"].utterances == [
        "seed cheap utterance",
        "generated cheap utterance",
    ]
    assert settings.routes["pro-router"].utterances == [
        "seed pro utterance",
        "generated pro utterance",
    ]
    assert "undeclared" not in settings.routes


def test_load_settings_ignores_missing_route_bank_by_default(tmp_path: Path):
    routes_path = tmp_path / "routes.yaml"
    routes_path.write_text(
        """
route_model: smart-router
default_route: cheap-router
route_bank_path: missing.yaml
routes:
  cheap-router:
    description: seed cheap
    utterances:
      - seed cheap utterance
""",
        encoding="utf-8",
    )

    settings = load_settings(routes_path)

    assert settings.routes["cheap-router"].utterances == ["seed cheap utterance"]


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
default_route: cheap-router
route_bank_path: data/semantic_sets/route_bank.yaml
routes:
  cheap-router:
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
  cheap-router:
    utterances:
      - text: generated cheap utterance
        source: cwd_bank
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    settings = load_settings(routes_path)

    assert settings.routes["cheap-router"].utterances == [
        "seed cheap utterance",
        "generated cheap utterance",
    ]


def test_default_hard_rules_keep_only_high_precision_strong_escalations():
    settings = load_settings("config/routes.yaml")

    keywords = [keyword for hard_rule in settings.hard_rules for keyword in hard_rule.keywords]
    assert "生产" not in keywords
    assert "线上" not in keywords
    assert "PR" not in keywords
    assert "部署" not in keywords
    assert "索引" not in keywords
    assert "异常" not in keywords
    assert "报错" not in keywords
    assert "线上事故" in keywords
    assert "密钥" in keywords
    assert settings.hard_rules[0].route_id == "strong"


def test_router_settings_defaults_entry_model_to_semantic_router():
    settings = RouterSettings(
        routes={
            "fast": RouteSpec(description="low risk", utterances=["x"]),
        }
    )
    assert settings.route_model == "semantic-router"
    assert settings.entry_model == "semantic-router"


def test_router_settings_accepts_legacy_route_model_config_key():
    settings = RouterSettings.model_validate(
        {
            "route_model": "smart-router",
            "routes": {"fast": {"description": "low risk", "utterances": ["x"]}},
        }
    )
    assert settings.route_model == "smart-router"


def test_load_settings_reads_litellm_timeout_override(tmp_path: Path, monkeypatch):
    routes_path = tmp_path / "routes.yaml"
    routes_path.write_text(
        """
route_model: semantic-router
default_route: cheap-router
routes:
  cheap-router:
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
fallback_route_id: runtime-fast
routes:
  runtime-fast:
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
    assert settings.routes["runtime-fast"].target_model == "runtime-target"


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
default_route: cheap-router
routes:
  cheap-router:
    description: seed cheap
    utterances:
      - seed cheap utterance
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("ROUTER_AUDIT_LOG_DIR", str(audit_dir))
    monkeypatch.setenv("ROUTER_AUDIT_LOG_ENABLED", "true")

    settings = load_settings(routes_path)

    assert settings.audit_log_dir == str(audit_dir)
    assert settings.audit_log_enabled is True


def test_load_settings_disables_access_log_by_default(tmp_path: Path):
    routes_path = tmp_path / "routes.yaml"
    routes_path.write_text(
        """
route_model: semantic-router
default_route: cheap-router
routes:
  cheap-router:
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
default_route: cheap-router
routes:
  cheap-router:
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
default_route: cheap-router
routes:
  cheap-router:
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
                "cheap-router": RouteSpec(
                    description="seed cheap",
                    utterances=["seed cheap utterance"],
                )
            },
        )


def test_router_settings_rejects_recursive_route_target():
    with pytest.raises(ValidationError, match="recursive"):
        RouterSettings(
            route_model="semantic-router",
            default_route="cheap-router",
            routes={
                "semantic-router": RouteSpec(
                    description="recursive target",
                    utterances=["send back to entry model"],
                ),
                "cheap-router": RouteSpec(
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
                description="local fast target",
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
            fallback_route_id="fast",
            routes={
                "fast": RouteSpec(
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
            "routes": {"fast": {"description": "low risk", "utterances": ["x"]}},
        }
    )
    assert settings.route_model == "smart-router"
    assert settings.entry_model == "smart-router"


def test_router_settings_prefers_route_model_when_both_alias_keys_present():
    settings = RouterSettings.model_validate(
        {
            "route_model": "route-model-wins",
            "entry_model": "entry-model-loses",
            "routes": {"fast": {"description": "low risk", "utterances": ["x"]}},
        }
    )

    assert settings.route_model == "route-model-wins"


def test_router_settings_accepts_fallback_route_id_key():
    settings = RouterSettings.model_validate(
        {
            "fallback_route_id": "fast",
            "routes": {"fast": {"description": "low risk", "utterances": ["x"]}},
        }
    )

    assert settings.fallback_route_id == "fast"
    assert settings.default_route == "fast"


def test_router_settings_accepts_default_route_legacy_alias_key():
    settings = RouterSettings.model_validate(
        {
            "default_route": "fast",
            "routes": {"fast": {"description": "low risk", "utterances": ["x"]}},
        }
    )

    assert settings.fallback_route_id == "fast"


def test_router_settings_defaults_target_model_to_route_id_when_omitted():
    settings = RouterSettings.model_validate(
        {
            "routes": {
                "fast": {"description": "low risk", "utterances": ["x"]},
                "strong": {"description": "high risk", "utterances": ["y"]},
            }
        }
    )

    assert settings.routes["fast"].target_model == "fast"
    assert settings.routes["strong"].target_model == "strong"


def test_router_settings_rejects_missing_fallback_route_id_in_routes():
    with pytest.raises(ValidationError, match="fallback_route_id must be present"):
        RouterSettings.model_validate(
            {
                "fallback_route_id": "missing",
                "routes": {
                    "fast": {"description": "low risk", "utterances": ["x"]},
                },
            }
        )
