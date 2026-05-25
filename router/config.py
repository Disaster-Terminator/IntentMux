from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import AliasChoices, BaseModel, Field, model_validator


DEFAULT_REPO_CONFIG = Path("config/routes.yaml")
DEFAULT_RUNTIME_HOME = Path(".intentmux-home")


def runtime_home_from_env() -> Path | None:
    raw = os.getenv("INTENTMUX_HOME")
    if not raw:
        return None
    return Path(raw).expanduser()


def default_runtime_home() -> Path:
    return runtime_home_from_env() or DEFAULT_RUNTIME_HOME


def runtime_home_for_config(
    config_path: Path | None = None,
    *,
    infer_from_config_path: bool = True,
) -> Path:
    explicit = runtime_home_from_env()
    if explicit is not None:
        return explicit
    if (
        infer_from_config_path
        and config_path is not None
        and config_path.parent.name == "config"
    ):
        return config_path.parent.parent
    return DEFAULT_RUNTIME_HOME


def runtime_path_from_home(*parts: str, runtime_home: Path | None = None) -> str | None:
    base = runtime_home or default_runtime_home()
    return str(base.joinpath(*parts))


def default_config_path() -> Path:
    configured = os.getenv("ROUTER_CONFIG")
    if configured:
        return Path(configured).expanduser()
    explicit_runtime_home = runtime_home_from_env()
    if explicit_runtime_home is not None:
        return explicit_runtime_home / "config" / "routes.yaml"
    runtime_config = DEFAULT_RUNTIME_HOME / "config" / "routes.yaml"
    if runtime_config.exists():
        return runtime_config
    return DEFAULT_REPO_CONFIG


class RouteSpec(BaseModel):
    target_model: str | None = None
    description: str
    utterances: list[str]
    utterance_sources: dict[str, str] = Field(default_factory=dict)


class HardRuleSpec(BaseModel):
    route_id: str
    keywords: list[str]


class RouterSettings(BaseModel):
    config_path: str | None = None
    config_source: str | None = None
    config_sha256: str | None = None
    route_bank_sha256: str | None = None
    runtime_home: str | None = None
    runtime_config_exists: bool = False
    placeholder_target_models: list[str] = Field(default_factory=list)
    # entry_model is the product-facing alias; route_model remains supported for
    # backward compatibility with existing routes.yaml deployments.
    # When both keys are present, route_model takes precedence via AliasChoices
    # ordering for deterministic compatibility.
    route_model: str = Field(
        default="intentmux",
        validation_alias=AliasChoices("route_model", "entry_model"),
    )
    entry_model_aliases: list[str] = Field(default_factory=list)
    route_id_aliases: dict[str, str] = Field(default_factory=dict)
    fallback_route_id: str = Field(
        default="lite",
        validation_alias=AliasChoices("fallback_route_id", "default_route"),
    )
    agent_signal_enabled: bool = True
    agent_signal_route_id: str | None = None
    agent_signal_min_input_chars: int = 12_000
    agent_signal_min_message_count: int = 6
    route_kernel: Literal["aurelio", "basic"] = "aurelio"
    aurelio_router: Literal["hybrid", "semantic"] = "hybrid"
    aurelio_hybrid_alpha: float = 0.3
    threshold: float = 0.4
    margin: float = 0.04
    routes: dict[str, RouteSpec]
    route_bank_path: str | None = None
    require_route_bank: bool = Field(
        default=False,
        validation_alias=AliasChoices("require_route_bank", "route_bank_required"),
    )
    route_bank_loaded: bool = False
    route_embedding_cache_enabled: bool = True
    route_embedding_cache_path: str | None = None
    hard_rules: list[HardRuleSpec] = Field(default_factory=list)
    embedding_url: str = "http://127.0.0.1:1234/v1/embeddings"
    embedding_model: str = "text-embedding-jina-embeddings-v5-text-small-retrieval@q8_0"
    embedding_batch_size: int = 128
    embedding_api_key: str | None = None
    embedding_headers: dict[str, str] = Field(default_factory=dict)
    litellm_base_url: str = "http://127.0.0.1:4000"
    litellm_api_key: str | None = None
    inbound_api_key: str | None = None
    inbound_api_keys: list[str] = Field(default_factory=list)
    cloud_mode: bool = False
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
        if not 0.0 < self.aurelio_hybrid_alpha <= 1.0:
            raise ValueError("aurelio_hybrid_alpha must be greater than 0 and at most 1")
        if (
            self.agent_signal_enabled
            and self.agent_signal_route_id is not None
            and self.agent_signal_route_id not in self.routes
        ):
            raise ValueError("agent_signal_route_id must be present in routes")

        for hard_rule in self.hard_rules:
            if hard_rule.route_id not in self.routes:
                raise ValueError("hard_rules route_id must be present in routes")
        self.inbound_api_keys = merged_api_keys(
            [self.inbound_api_key],
            self.inbound_api_keys,
        )
        if self.inbound_api_key is None and self.inbound_api_keys:
            self.inbound_api_key = self.inbound_api_keys[0]
        if self.cloud_mode and not self.inbound_api_keys:
            raise ValueError("inbound_api_key is required in cloud mode")
        if self.cloud_mode and self.prompt_log_mode == "raw_local":
            raise ValueError("raw_local prompt logging is not allowed in cloud mode")
        if self.cloud_mode and self.placeholder_target_models:
            raise ValueError("placeholder target models are not allowed in cloud mode")
        if self.prompt_log_mode != "off" and not self.prompt_log_dir:
            raise ValueError("prompt_log_dir is required when prompt logging is enabled")
        if self.prompt_log_max_chars <= 0:
            raise ValueError("prompt_log_max_chars must be positive")
        if self.embedding_batch_size <= 0:
            raise ValueError("embedding_batch_size must be positive")
        if self.listen_port <= 0:
            raise ValueError("listen_port must be positive")
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
    config_path = Path(path).expanduser() if path is not None else default_config_path()
    if not config_path.exists():
        raise FileNotFoundError(f"router config not found: {config_path}")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    infer_runtime_home = (
        path is not None
        or os.getenv("ROUTER_CONFIG") is not None
        or config_path == DEFAULT_RUNTIME_HOME / "config" / "routes.yaml"
    )
    runtime_home = runtime_home_for_config(
        config_path,
        infer_from_config_path=infer_runtime_home,
    )
    apply_runtime_home_defaults(raw, runtime_home=runtime_home)
    require_route_bank = bool_from_env(
        "ROUTER_REQUIRE_ROUTE_BANK",
        bool_from_value(raw.get("require_route_bank", raw.get("route_bank_required", False))),
    )
    raw["require_route_bank"] = require_route_bank
    raw = merge_route_bank(raw, config_path.parent, require_route_bank=require_route_bank)
    settings = RouterSettings.model_validate(raw)
    inbound_api_key = os.getenv("ROUTER_INBOUND_API_KEY") or settings.inbound_api_key
    overrides = {
        "embedding_url": os.getenv("ROUTER_EMBEDDING_URL", settings.embedding_url),
        "embedding_model": os.getenv("ROUTER_EMBEDDING_MODEL", settings.embedding_model),
        "embedding_batch_size": int(
            os.getenv("ROUTER_EMBEDDING_BATCH_SIZE", str(settings.embedding_batch_size))
        ),
        "embedding_api_key": os.getenv("ROUTER_EMBEDDING_API_KEY")
        or settings.embedding_api_key,
        "embedding_headers": headers_from_json_env(
            "ROUTER_EMBEDDING_HEADERS_JSON",
            settings.embedding_headers,
        ),
        "route_embedding_cache_enabled": bool_from_env(
            "ROUTER_ROUTE_EMBEDDING_CACHE_ENABLED",
            settings.route_embedding_cache_enabled,
        ),
        "route_embedding_cache_path": os.getenv(
            "ROUTER_ROUTE_EMBEDDING_CACHE_PATH",
            settings.route_embedding_cache_path
            or runtime_path_from_home("cache", "route-embeddings.json", runtime_home=runtime_home)
            or "",
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
        "route_kernel": os.getenv("ROUTER_ROUTE_KERNEL", settings.route_kernel),
        "aurelio_router": os.getenv("ROUTER_AURELIO_ROUTER", settings.aurelio_router),
        "aurelio_hybrid_alpha": float(
            os.getenv("ROUTER_AURELIO_HYBRID_ALPHA", str(settings.aurelio_hybrid_alpha))
        ),
        "litellm_base_url": os.getenv("ROUTER_LITELLM_BASE_URL", settings.litellm_base_url),
        "litellm_api_key": os.getenv("ROUTER_LITELLM_API_KEY") or settings.litellm_api_key,
        "inbound_api_key": inbound_api_key,
        "inbound_api_keys": inbound_api_keys_from_env(
            inbound_api_key=inbound_api_key,
            existing=settings.inbound_api_keys,
        ),
        "cloud_mode": bool_from_env("ROUTER_CLOUD_MODE", settings.cloud_mode),
        "litellm_timeout": float(
            os.getenv("ROUTER_LITELLM_TIMEOUT", str(settings.litellm_timeout))
        ),
        "access_log": bool_from_env("ROUTER_ACCESS_LOG", settings.access_log),
        "audit_log_enabled": bool_from_env(
            "ROUTER_AUDIT_LOG_ENABLED", settings.audit_log_enabled
        ),
        "audit_log_dir": os.getenv(
            "ROUTER_AUDIT_LOG_DIR",
            settings.audit_log_dir
            or runtime_path_from_home("logs", "routes", runtime_home=runtime_home)
            or "",
        ),
        "audit_log_timezone": os.getenv(
            "ROUTER_AUDIT_LOG_TIMEZONE",
            settings.audit_log_timezone,
        ),
        "prompt_log_mode": os.getenv("ROUTER_PROMPT_LOG_MODE", settings.prompt_log_mode),
        "prompt_log_dir": os.getenv(
            "ROUTER_PROMPT_LOG_DIR",
            settings.prompt_log_dir
            or runtime_path_from_home("logs", "prompts", runtime_home=runtime_home)
            or "",
        ),
        "prompt_log_max_chars": int(
            os.getenv("ROUTER_PROMPT_LOG_MAX_CHARS", str(settings.prompt_log_max_chars))
        ),
        "readiness_timeout": float(
            os.getenv("ROUTER_READINESS_TIMEOUT", str(settings.readiness_timeout))
        ),
        "listen_host": os.getenv("ROUTER_HOST", settings.listen_host),
        "listen_port": listen_port_from_env(settings.listen_port),
    }
    return RouterSettings.model_validate(
        settings.model_dump()
        | overrides
        | config_diagnostics(
            config_path,
            path=path,
            runtime_home=runtime_home,
            route_bank_path=settings.route_bank_path,
        )
    )


def config_diagnostics(
    config_path: Path,
    *,
    path: str | Path | None = None,
    runtime_home: Path | None = None,
    route_bank_path: str | None = None,
) -> dict[str, Any]:
    runtime_home = runtime_home or runtime_home_for_config(config_path)
    return {
        "config_path": str(config_path),
        "config_source": config_source(config_path, path=path),
        "config_sha256": sha256_file(config_path),
        "route_bank_sha256": route_bank_sha256(route_bank_path, config_path.parent),
        "runtime_home": str(runtime_home),
        "runtime_config_exists": (runtime_home / "config" / "routes.yaml").exists(),
        "placeholder_target_models": placeholder_target_models(config_path),
    }


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def route_bank_sha256(route_bank_path: str | None, base_dir: Path) -> str | None:
    if not route_bank_path:
        return None
    resolved = resolve_route_bank_path(route_bank_path, base_dir)
    if not resolved.exists():
        return None
    return sha256_file(resolved)


def inbound_api_keys_from_env(
    *,
    inbound_api_key: str | None,
    existing: list[str],
) -> list[str]:
    return merged_api_keys(
        [inbound_api_key],
        [os.getenv("ROUTER_INBOUND_API_KEY_NEXT")],
        split_csv(os.getenv("ROUTER_INBOUND_API_KEYS")),
        existing,
    )


def split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",")]


def merged_api_keys(*groups: list[str | None] | list[str]) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for key in group:
            if not key or key in seen:
                continue
            keys.append(key)
            seen.add(key)
    return keys


def config_source(config_path: Path, *, path: str | Path | None = None) -> str:
    if path is not None:
        return "argument"
    if os.getenv("ROUTER_CONFIG"):
        return "ROUTER_CONFIG"
    if runtime_home_from_env() is not None:
        return "INTENTMUX_HOME"
    runtime_config = DEFAULT_RUNTIME_HOME / "config" / "routes.yaml"
    if config_path == runtime_config:
        return "default_runtime_home"
    return "repo_default"


def placeholder_target_models(config_path: Path) -> list[str]:
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    routes = raw.get("routes") or {}
    placeholders: list[str] = []
    for route_id, route in routes.items():
        if not isinstance(route, dict):
            continue
        target_model = route.get("target_model")
        if isinstance(target_model, str) and target_model.startswith("your-"):
            placeholders.append(f"{route_id}:{target_model}")
    return placeholders


def apply_runtime_home_defaults(raw: dict[str, Any], *, runtime_home: Path | None = None) -> None:
    raw.setdefault(
        "audit_log_dir",
        runtime_path_from_home("logs", "routes", runtime_home=runtime_home),
    )
    prompt_mode = os.getenv("ROUTER_PROMPT_LOG_MODE", raw.get("prompt_log_mode", "off"))
    if prompt_mode != "off":
        raw.setdefault(
            "prompt_log_dir",
            runtime_path_from_home("logs", "prompts", runtime_home=runtime_home),
        )


def bool_from_value(value: Any) -> bool:
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def bool_from_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def listen_port_from_env(default: int) -> int:
    for name in ("ROUTER_PORT", "CONTAINER_APP_PORT", "PORT"):
        value = os.getenv(name)
        if value:
            return int(value)
    return default


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
        existing_sources = dict(route_config.get("utterance_sources", {}))
        seen = set(existing)
        for item in route_bank.get("utterances", []):
            text = item.get("text") if isinstance(item, dict) else item
            if not text:
                continue
            matched_utterances += 1
            if text not in seen:
                existing.append(text)
                seen.add(text)
            if isinstance(item, dict) and isinstance(item.get("source"), str):
                existing_sources[str(text)] = item["source"]
        route_config["utterances"] = existing
        route_config["utterance_sources"] = existing_sources
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
