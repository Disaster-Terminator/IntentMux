from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import AliasChoices, BaseModel, Field, model_validator


class RouteSpec(BaseModel):
    target_model: str | None = None
    description: str
    utterances: list[str]


class HardRuleSpec(BaseModel):
    route_id: str
    keywords: list[str]


class RouterSettings(BaseModel):
    # entry_model is the product-facing alias; route_model remains supported for
    # backward compatibility with existing routes.yaml deployments.
    # When both keys are present, route_model takes precedence via AliasChoices
    # ordering for deterministic compatibility.
    route_model: str = Field(
        default="semantic-router",
        validation_alias=AliasChoices("route_model", "entry_model"),
    )
    entry_model_aliases: list[str] = Field(
        default_factory=lambda: ["auto", "semantic-router"]
    )
    route_id_aliases: dict[str, str] = Field(default_factory=dict)
    fallback_route_id: str = Field(
        default="lite",
        validation_alias=AliasChoices("fallback_route_id", "default_route"),
    )
    agent_signal_enabled: bool = True
    agent_signal_route_id: str | None = None
    agent_signal_min_input_chars: int = 12_000
    agent_signal_min_message_count: int = 6
    threshold: float = 0.55
    margin: float = 0.04
    routes: dict[str, RouteSpec]
    route_bank_path: str | None = None
    require_route_bank: bool = Field(
        default=False,
        validation_alias=AliasChoices("require_route_bank", "route_bank_required"),
    )
    route_bank_loaded: bool = False
    hard_rules: list[HardRuleSpec] = Field(default_factory=list)
    embedding_url: str = "http://127.0.0.1:1234/v1/embeddings"
    embedding_model: str = "text-embedding-jina-embeddings-v5-text-small-retrieval@q8_0"
    embedding_api_key: str | None = None
    embedding_headers: dict[str, str] = Field(default_factory=dict)
    litellm_base_url: str = "http://127.0.0.1:4000"
    litellm_api_key: str | None = None
    inbound_api_key: str | None = None
    litellm_timeout: float = 120.0
    access_log: bool = False
    audit_log_enabled: bool = False
    audit_log_dir: str | None = None
    audit_log_timezone: str = "Asia/Shanghai"
    prompt_log_mode: Literal["off", "redacted", "raw_local"] = "off"
    prompt_log_dir: str | None = None
    prompt_log_max_chars: int = 20_000
    readiness_timeout: float = 2.0
    listen_host: str = "127.0.0.1"
    listen_port: int = 4001

    @model_validator(mode="after")
    def validate_route_contract(self) -> "RouterSettings":
        self.fallback_route_id = self.resolve_route_id_alias(self.fallback_route_id)
        if self.agent_signal_route_id is not None:
            self.agent_signal_route_id = self.resolve_route_id_alias(
                self.agent_signal_route_id
            )
        for hard_rule in self.hard_rules:
            hard_rule.route_id = self.resolve_route_id_alias(hard_rule.route_id)

        if self.fallback_route_id == self.route_model:
            raise ValueError("fallback_route_id must not point back to route_model")
        if self.route_model in self.routes:
            raise ValueError("recursive route config: route_model must not be a route_id")

        for route_id, route_spec in self.routes.items():
            if route_spec.target_model is None:
                route_spec.target_model = route_id
            if route_spec.target_model == self.route_model:
                raise ValueError("recursive route config: target_model must not be route_model")

        if self.fallback_route_id not in self.routes:
            raise ValueError("fallback_route_id must be present in routes")
        if self.agent_signal_min_input_chars <= 0:
            raise ValueError("agent_signal_min_input_chars must be positive")
        if self.agent_signal_min_message_count <= 0:
            raise ValueError("agent_signal_min_message_count must be positive")
        if (
            self.agent_signal_enabled
            and self.agent_signal_route_id is not None
            and self.agent_signal_route_id not in self.routes
        ):
            raise ValueError("agent_signal_route_id must be present in routes")

        for hard_rule in self.hard_rules:
            if hard_rule.route_id not in self.routes:
                raise ValueError("hard_rules route_id must be present in routes")
        if self.prompt_log_mode != "off" and not self.prompt_log_dir:
            raise ValueError("prompt_log_dir is required when prompt logging is enabled")
        if self.prompt_log_max_chars <= 0:
            raise ValueError("prompt_log_max_chars must be positive")
        return self

    def resolve_route_id_alias(self, route_id: str) -> str:
        if route_id in self.routes:
            return route_id
        alias_target = self.route_id_aliases.get(route_id)
        if alias_target in self.routes:
            return alias_target
        return route_id

    @property
    def default_route(self) -> str:
        return self.fallback_route_id

    @property
    def entry_model(self) -> str:
        return self.route_model

    @property
    def effective_agent_signal_route_id(self) -> str | None:
        if not self.agent_signal_enabled:
            return None
        if self.agent_signal_route_id is not None:
            return self.agent_signal_route_id
        if "deep" in self.routes:
            return "deep"
        return None


def load_settings(path: str | Path | None = None) -> RouterSettings:
    config_path = Path(path or os.getenv("ROUTER_CONFIG", "config/routes.yaml"))
    if not config_path.exists():
        raise FileNotFoundError(f"router config not found: {config_path}")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    require_route_bank = bool_from_env(
        "ROUTER_REQUIRE_ROUTE_BANK",
        bool_from_value(raw.get("require_route_bank", raw.get("route_bank_required", False))),
    )
    raw["require_route_bank"] = require_route_bank
    raw = merge_route_bank(raw, config_path.parent, require_route_bank=require_route_bank)
    settings = RouterSettings.model_validate(raw)
    overrides = {
        "embedding_url": os.getenv("ROUTER_EMBEDDING_URL", settings.embedding_url),
        "embedding_model": os.getenv("ROUTER_EMBEDDING_MODEL", settings.embedding_model),
        "embedding_api_key": os.getenv("ROUTER_EMBEDDING_API_KEY")
        or settings.embedding_api_key,
        "embedding_headers": headers_from_json_env(
            "ROUTER_EMBEDDING_HEADERS_JSON",
            settings.embedding_headers,
        ),
        "agent_signal_enabled": bool_from_env(
            "ROUTER_AGENT_SIGNAL_ENABLED",
            settings.agent_signal_enabled,
        ),
        "agent_signal_route_id": os.getenv(
            "ROUTER_AGENT_SIGNAL_ROUTE_ID",
            settings.agent_signal_route_id,
        ),
        "agent_signal_min_input_chars": int(
            os.getenv(
                "ROUTER_AGENT_SIGNAL_MIN_INPUT_CHARS",
                str(settings.agent_signal_min_input_chars),
            )
        ),
        "agent_signal_min_message_count": int(
            os.getenv(
                "ROUTER_AGENT_SIGNAL_MIN_MESSAGE_COUNT",
                str(settings.agent_signal_min_message_count),
            )
        ),
        "litellm_base_url": os.getenv("ROUTER_LITELLM_BASE_URL", settings.litellm_base_url),
        "litellm_api_key": os.getenv("ROUTER_LITELLM_API_KEY") or settings.litellm_api_key,
        "inbound_api_key": os.getenv("ROUTER_INBOUND_API_KEY") or settings.inbound_api_key,
        "litellm_timeout": float(
            os.getenv("ROUTER_LITELLM_TIMEOUT", str(settings.litellm_timeout))
        ),
        "access_log": bool_from_env("ROUTER_ACCESS_LOG", settings.access_log),
        "audit_log_enabled": bool_from_env(
            "ROUTER_AUDIT_LOG_ENABLED", settings.audit_log_enabled
        ),
        "audit_log_dir": os.getenv("ROUTER_AUDIT_LOG_DIR", settings.audit_log_dir or ""),
        "audit_log_timezone": os.getenv(
            "ROUTER_AUDIT_LOG_TIMEZONE",
            settings.audit_log_timezone,
        ),
        "prompt_log_mode": os.getenv("ROUTER_PROMPT_LOG_MODE", settings.prompt_log_mode),
        "prompt_log_dir": os.getenv("ROUTER_PROMPT_LOG_DIR", settings.prompt_log_dir or ""),
        "prompt_log_max_chars": int(
            os.getenv("ROUTER_PROMPT_LOG_MAX_CHARS", str(settings.prompt_log_max_chars))
        ),
        "readiness_timeout": float(
            os.getenv("ROUTER_READINESS_TIMEOUT", str(settings.readiness_timeout))
        ),
        "listen_host": os.getenv("ROUTER_HOST", settings.listen_host),
        "listen_port": int(os.getenv("ROUTER_PORT", str(settings.listen_port))),
    }
    return RouterSettings.model_validate(settings.model_dump() | overrides)


def bool_from_value(value: Any) -> bool:
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def bool_from_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def headers_from_json_env(name: str, default: dict[str, str]) -> dict[str, str]:
    value = os.getenv(name)
    if value is None or value == "":
        return dict(default)
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} must be a JSON object of string headers") from exc
    if not isinstance(parsed, dict) or not all(
        isinstance(key, str) and isinstance(header_value, str)
        for key, header_value in parsed.items()
    ):
        raise ValueError(f"{name} must be a JSON object of string headers")
    return dict(parsed)


def merge_route_bank(raw: dict, base_dir: Path, *, require_route_bank: bool = False) -> dict:
    route_bank_path = raw.get("route_bank_path")
    if not route_bank_path:
        if require_route_bank:
            raise ValueError("require_route_bank is true but route_bank_path is not set")
        return raw

    bank_path = resolve_route_bank_path(route_bank_path, base_dir)
    if not bank_path.exists():
        if require_route_bank:
            raise FileNotFoundError(f"required route bank not found: {bank_path}")
        return raw

    bank = yaml.safe_load(bank_path.read_text(encoding="utf-8"))
    if not isinstance(bank, dict):
        if require_route_bank:
            raise ValueError("required route bank did not add utterances")
        return raw
    raw_routes = raw.setdefault("routes", {})
    bank_routes = bank.get("routes", {})
    if not isinstance(bank_routes, dict):
        if require_route_bank:
            raise ValueError("required route bank did not add utterances")
        return raw
    matched_utterances = 0
    for route_name, route_bank in bank_routes.items():
        if route_name not in raw_routes:
            continue
        if not isinstance(route_bank, dict):
            continue
        route_config = raw_routes[route_name]
        existing = list(route_config.get("utterances", []))
        seen = set(existing)
        for item in route_bank.get("utterances", []):
            text = item.get("text") if isinstance(item, dict) else item
            if not text:
                continue
            matched_utterances += 1
            if text not in seen:
                existing.append(text)
                seen.add(text)
        route_config["utterances"] = existing
    if require_route_bank and matched_utterances == 0:
        raise ValueError("required route bank did not provide utterances")
    raw["route_bank_loaded"] = matched_utterances > 0
    return raw


def resolve_route_bank_path(route_bank_path: str, base_dir: Path) -> Path:
    bank_path = Path(route_bank_path)
    if bank_path.is_absolute():
        return bank_path

    config_relative_path = base_dir / bank_path
    if config_relative_path.exists():
        return config_relative_path
    return bank_path
