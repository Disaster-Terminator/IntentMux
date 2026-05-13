from __future__ import annotations

from dataclasses import dataclass

import httpx

from router.config import RouterSettings
from router.embedding import build_embedding_headers


@dataclass(frozen=True)
class ComponentStatus:
    ok: bool
    detail: str | None = None


@dataclass(frozen=True)
class ReadinessReport:
    ready: bool
    components: dict[str, ComponentStatus]

    def to_dict(self) -> dict:
        return {
            "ready": self.ready,
            "components": {
                name: {
                    "ok": status.ok,
                    "detail": status.detail,
                }
                for name, status in self.components.items()
            },
        }


class ReadinessChecker:
    def __init__(self, settings: RouterSettings):
        self.settings = settings

    async def check(self) -> ReadinessReport:
        components = {
            "router": self.check_router(),
            "litellm": await self.check_litellm(),
            "embedding": await self.check_embedding(),
        }
        return ReadinessReport(
            ready=all(component.ok for component in components.values()),
            components=components,
        )

    def check_router(self) -> ComponentStatus:
        route_counts = ",".join(
            f"{route_id}:{len(route.utterances)}"
            for route_id, route in sorted(self.settings.routes.items())
        )
        route_bank_loaded = "true" if self.settings.route_bank_loaded else "false"
        return ComponentStatus(
            ok=True,
            detail=f"route_bank_loaded={route_bank_loaded} route_utterances={route_counts}",
        )

    async def check_litellm(self) -> ComponentStatus:
        try:
            async with httpx.AsyncClient(timeout=self.settings.readiness_timeout) as client:
                response = await client.get(f"{self.settings.litellm_base_url.rstrip('/')}/health")
        except Exception as exc:
            return ComponentStatus(ok=False, detail=type(exc).__name__)
        return litellm_status_from_code(response.status_code)

    async def check_embedding(self) -> ComponentStatus:
        try:
            async with httpx.AsyncClient(timeout=self.settings.readiness_timeout) as client:
                response = await client.post(
                    self.settings.embedding_url,
                    json={
                        "model": self.settings.embedding_model,
                        "input": ["ping"],
                    },
                    headers=build_embedding_headers(
                        api_key=self.settings.embedding_api_key,
                        custom_headers=self.settings.embedding_headers,
                    ),
                )
        except Exception as exc:
            return ComponentStatus(ok=False, detail=type(exc).__name__)
        return ComponentStatus(
            ok=200 <= response.status_code < 300,
            detail=f"status={response.status_code}",
        )


def litellm_status_from_code(status_code: int) -> ComponentStatus:
    if status_code in {401, 403}:
        return ComponentStatus(ok=True, detail=f"status={status_code} auth_required")
    return ComponentStatus(
        ok=200 <= status_code < 300,
        detail=f"status={status_code}",
    )
