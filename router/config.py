from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class RouteSpec(BaseModel):
    description: str
    utterances: list[str]


class RouterSettings(BaseModel):
    route_model: str = "smart-router"
    default_route: str = "cheap-router"
    threshold: float = 0.55
    margin: float = 0.04
    routes: dict[str, RouteSpec]
    route_bank_path: str | None = None
    pro_hard_rules: list[str] = Field(default_factory=list)
    embedding_url: str = "http://127.0.0.1:1234/v1/embeddings"
    embedding_model: str = "text-embedding-jina-embeddings-v5-text-small-retrieval@q8_0"
    litellm_base_url: str = "http://127.0.0.1:4000"
    litellm_timeout: float = 120.0
    access_log: bool = False
    readiness_timeout: float = 2.0
    listen_host: str = "127.0.0.1"
    listen_port: int = 4001


def load_settings(path: str | Path = "config/routes.yaml") -> RouterSettings:
    config_path = Path(path)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    raw = merge_route_bank(raw, config_path.parent)
    settings = RouterSettings.model_validate(raw)
    return settings.model_copy(
        update={
            "embedding_url": os.getenv("ROUTER_EMBEDDING_URL", settings.embedding_url),
            "embedding_model": os.getenv("ROUTER_EMBEDDING_MODEL", settings.embedding_model),
            "litellm_base_url": os.getenv("ROUTER_LITELLM_BASE_URL", settings.litellm_base_url),
            "litellm_timeout": float(
                os.getenv("ROUTER_LITELLM_TIMEOUT", str(settings.litellm_timeout))
            ),
            "access_log": bool_from_env("ROUTER_ACCESS_LOG", settings.access_log),
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
        route_config = raw_routes.setdefault(
            route_name,
            {
                "description": f"generated route bank for {route_name}",
                "utterances": [],
            },
        )
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
