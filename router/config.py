from __future__ import annotations

import os
from pathlib import Path

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
    fallback_route_id: str = Field(
        default="fast",
        validation_alias=AliasChoices("fallback_route_id", "default_route"),
    )
    threshold: float = 0.55
    margin: float = 0.04
    routes: dict[str, RouteSpec]
    route_bank_path: str | None = None
    hard_rules: list[HardRuleSpec] = Field(default_factory=list)
    embedding_url: str = "http://127.0.0.1:1234/v1/embeddings"
    embedding_model: str = "text-embedding-jina-embeddings-v5-text-small-retrieval@q8_0"
    litellm_base_url: str = "http://127.0.0.1:4000"
    litellm_api_key: str | None = None
    litellm_timeout: float = 120.0
    access_log: bool = False
    audit_log_enabled: bool = False
    audit_log_dir: str | None = None
    readiness_timeout: float = 2.0
    listen_host: str = "127.0.0.1"
    listen_port: int = 4001

    @model_validator(mode="after")
    def validate_route_contract(self) -> "RouterSettings":
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

        for hard_rule in self.hard_rules:
            if hard_rule.route_id not in self.routes:
                raise ValueError("hard_rules route_id must be present in routes")
        return self

    @property
    def default_route(self) -> str:
        return self.fallback_route_id

    @property
    def entry_model(self) -> str:
        return self.route_model


def load_settings(path: str | Path | None = None) -> RouterSettings:
    config_path = Path(path or os.getenv("ROUTER_CONFIG", "config/routes.yaml"))
    if not config_path.exists():
        raise FileNotFoundError(f"router config not found: {config_path}")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    raw = merge_route_bank(raw, config_path.parent)
    settings = RouterSettings.model_validate(raw)
    return settings.model_copy(
        update={
            "embedding_url": os.getenv("ROUTER_EMBEDDING_URL", settings.embedding_url),
            "embedding_model": os.getenv("ROUTER_EMBEDDING_MODEL", settings.embedding_model),
            "litellm_base_url": os.getenv("ROUTER_LITELLM_BASE_URL", settings.litellm_base_url),
            "litellm_api_key": os.getenv("ROUTER_LITELLM_API_KEY") or settings.litellm_api_key,
            "litellm_timeout": float(
                os.getenv("ROUTER_LITELLM_TIMEOUT", str(settings.litellm_timeout))
            ),
            "access_log": bool_from_env("ROUTER_ACCESS_LOG", settings.access_log),
            "audit_log_enabled": bool_from_env(
                "ROUTER_AUDIT_LOG_ENABLED", settings.audit_log_enabled
            ),
            "audit_log_dir": os.getenv("ROUTER_AUDIT_LOG_DIR", settings.audit_log_dir or ""),
            "readiness_timeout": float(
                os.getenv("ROUTER_READINESS_TIMEOUT", str(settings.readiness_timeout))
            ),
            "listen_host": os.getenv("ROUTER_HOST", settings.listen_host),
            "listen_port": int(os.getenv("ROUTER_PORT", str(settings.listen_port))),
        }
    )


def bool_from_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def merge_route_bank(raw: dict, base_dir: Path) -> dict:
    route_bank_path = raw.get("route_bank_path")
    if not route_bank_path:
        return raw

    bank_path = resolve_route_bank_path(route_bank_path, base_dir)
    if not bank_path.exists():
        return raw

    bank = yaml.safe_load(bank_path.read_text(encoding="utf-8"))
    raw_routes = raw.setdefault("routes", {})
    for route_name, route_bank in bank.get("routes", {}).items():
        if route_name not in raw_routes:
            continue
        route_config = raw_routes[route_name]
        existing = list(route_config.get("utterances", []))
        seen = set(existing)
        for item in route_bank.get("utterances", []):
            text = item.get("text") if isinstance(item, dict) else item
            if text and text not in seen:
                existing.append(text)
                seen.add(text)
        route_config["utterances"] = existing
    return raw


def resolve_route_bank_path(route_bank_path: str, base_dir: Path) -> Path:
    bank_path = Path(route_bank_path)
    if bank_path.is_absolute():
        return bank_path

    config_relative_path = base_dir / bank_path
    if config_relative_path.exists():
        return config_relative_path
    return bank_path
