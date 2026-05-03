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
    pro_hard_rules: list[str] = Field(default_factory=list)
    embedding_url: str = "http://127.0.0.1:1234/v1/embeddings"
    embedding_model: str = "text-embedding-jina-embeddings-v5-text-small-retrieval@q8_0"
    litellm_base_url: str = "http://127.0.0.1:4000"
    listen_host: str = "127.0.0.1"
    listen_port: int = 4001


def load_settings(path: str | Path = "config/routes.yaml") -> RouterSettings:
    config_path = Path(path)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    settings = RouterSettings.model_validate(raw)
    return settings.model_copy(
        update={
            "embedding_url": os.getenv("ROUTER_EMBEDDING_URL", settings.embedding_url),
            "embedding_model": os.getenv("ROUTER_EMBEDDING_MODEL", settings.embedding_model),
            "litellm_base_url": os.getenv("ROUTER_LITELLM_BASE_URL", settings.litellm_base_url),
            "listen_host": os.getenv("ROUTER_HOST", settings.listen_host),
            "listen_port": int(os.getenv("ROUTER_PORT", str(settings.listen_port))),
        }
    )

