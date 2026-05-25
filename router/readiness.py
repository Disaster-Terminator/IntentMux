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
        runtime_config_exists = (
            "true" if self.settings.runtime_config_exists else "false"
        )
        warnings = []
        if self.settings.config_source == "repo_default" and not self.settings.runtime_config_exists:
            warnings.append("runtime_config_missing")
        if self.settings.placeholder_target_models:
            warnings.append("placeholder_targets")
        if self.settings.cloud_mode:
            detail_parts = [
                "cloud_mode=true",
                f"config_source={self.settings.config_source}",
                f"runtime_config_exists={runtime_config_exists}",
                f"audit_log_enabled={str(self.settings.audit_log_enabled).lower()}",
                f"access_log={str(self.settings.access_log).lower()}",
                f"prompt_log_mode={self.settings.prompt_log_mode}",
            ]
        else:
            detail_parts = [
                f"config_source={self.settings.config_source}",
                f"config_path={self.settings.config_path}",
                f"runtime_home={self.settings.runtime_home}",
                f"runtime_config_exists={runtime_config_exists}",
                f"audit_log_enabled={str(self.settings.audit_log_enabled).lower()}",
                f"audit_log_dir={self.settings.audit_log_dir}",
                f"access_log={str(self.settings.access_log).lower()}",
                f"prompt_log_mode={self.settings.prompt_log_mode}",
            ]
        if self.settings.config_sha256:
            detail_parts.append(f"config_sha256={self.settings.config_sha256}")
        if self.settings.route_bank_sha256:
            detail_parts.append(f"route_bank_sha256={self.settings.route_bank_sha256}")
        if warnings:
            detail_parts.append(f"warnings={','.join(warnings)}")
        if self.settings.placeholder_target_models:
            detail_parts.append(
                "placeholder_target_models="
                + ",".join(self.settings.placeholder_target_models)
            )
        detail_parts.extend(
            [
                f"route_bank_loaded={route_bank_loaded}",
                f"route_utterances={route_counts}",
            ]
        )
        return ComponentStatus(
            ok=True,
            detail=" ".join(detail_parts),
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
