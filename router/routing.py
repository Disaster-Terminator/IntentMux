from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from router.config import RouterSettings
from router.embedding import EmbeddingClient


AGENT_INSTRUCTION_BOILERPLATE_MARKERS = (
    "<extremely_important> you have superpowers",
    "using-superpowers skill content",
    "<subagent-stop>",
    "## instruction priority",
    "<system-reminder>",
    "absolute constraint",
)


@dataclass(frozen=True)
class RoutingDecision:
    target_model: str
    reason: str
    rewrite: bool
    route_id: str | None = None
    policy_id: str | None = None
    source_model: str | None = None
    score: float | None = None
    second_score: float | None = None


class Router:
    def __init__(self, settings: RouterSettings, embedding_client: EmbeddingClient):
        self.settings = settings
        self.embedding_client = embedding_client
        self._route_vectors: dict[str, list[list[float]]] | None = None

    async def decide(
        self,
        request_json: dict[str, Any],
        format_signals: dict[str, Any] | None = None,
    ) -> RoutingDecision:
        source_model = request_json.get("model")
        requested_route_id = self._requested_route_id(source_model)
        if requested_route_id is not None:
            return RoutingDecision(
                route_id=requested_route_id,
                target_model=self._target_model_for_route(requested_route_id),
                source_model=source_model,
                reason="explicit",
                policy_id="explicit",
                rewrite=True,
            )

        if not self._is_entry_model(source_model):
            return RoutingDecision(
                target_model=source_model,
                source_model=source_model,
                reason="passthrough",
                policy_id="passthrough",
                rewrite=False,
            )

        explicit_route = self._explicit_route(request_json)
        if explicit_route:
            target_model = self._target_model_for_route(explicit_route)
            return RoutingDecision(
                route_id=explicit_route,
                target_model=target_model,
                source_model=source_model,
                reason="explicit",
                policy_id="explicit",
                rewrite=True,
            )

        text = latest_user_text(request_json.get("messages", []))
        hard_rule_text = "" if looks_like_agent_instruction_boilerplate(text) else text
        hard_rule = self._matching_hard_rule(hard_rule_text)
        if hard_rule:
            route_id, keyword = hard_rule
            return RoutingDecision(
                route_id=route_id,
                target_model=self._target_model_for_route(route_id),
                source_model=source_model,
                reason=f"hard_rule:{keyword}",
                policy_id="hard_rule",
                rewrite=True,
            )

        try:
            await self._ensure_route_vectors()
            query_vector = (await self.embedding_client.embed([text]))[0]
            route_scores = {
                route: max(cosine_similarity(query_vector, vector) for vector in vectors)
                for route, vectors in self._route_vectors.items()
                if vectors
            }
        except Exception:
            return RoutingDecision(
                route_id=self.settings.fallback_route_id,
                target_model=self._target_model_for_route(self.settings.fallback_route_id),
                source_model=source_model,
                reason="embedding_error",
                policy_id="embedding_error",
                rewrite=True,
            )

        if not route_scores:
            return RoutingDecision(
                route_id=self.settings.fallback_route_id,
                target_model=self._target_model_for_route(self.settings.fallback_route_id),
                source_model=source_model,
                reason="low_confidence",
                policy_id="low_confidence",
                rewrite=True,
                score=0.0,
                second_score=0.0,
            )

        ranked = sorted(route_scores.items(), key=lambda item: item[1], reverse=True)
        best_route, best_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0.0
        if (
            best_score < self.settings.threshold
            or best_score - second_score < self.settings.margin
        ):
            return RoutingDecision(
                route_id=self.settings.fallback_route_id,
                target_model=self._target_model_for_route(self.settings.fallback_route_id),
                source_model=source_model,
                reason="low_confidence",
                policy_id="low_confidence",
                rewrite=True,
                score=round(best_score, 6),
                second_score=round(second_score, 6),
            )

        return RoutingDecision(
            route_id=best_route,
            target_model=self._target_model_for_route(best_route),
            source_model=source_model,
            reason="embedding",
            policy_id="embedding",
            rewrite=True,
            score=round(best_score, 6),
            second_score=round(second_score, 6),
        )

    def _is_entry_model(self, source_model: Any) -> bool:
        return isinstance(source_model, str) and (
            source_model == self.settings.route_model
            or source_model in self.settings.entry_model_aliases
        )

    def _requested_route_id(self, source_model: Any) -> str | None:
        if not isinstance(source_model, str):
            return None
        return self._canonical_route_id(source_model)

    def _canonical_route_id(self, route: Any) -> str | None:
        if not isinstance(route, str):
            return None
        if route in self.settings.routes:
            return route
        alias_target = self.settings.resolve_route_id_alias(route)
        if alias_target in self.settings.routes:
            return alias_target
        return None

    def _explicit_route(self, request_json: dict[str, Any]) -> str | None:
        metadata = request_json.get("metadata")
        if not isinstance(metadata, dict):
            return None
        # route_id is the product-level explicit route override.
        # route and target_route are retained for backward compatibility, with
        # target_route treated as deprecated legacy metadata.
        route = (
            metadata.get("route_id")
            or metadata.get("route")
            or metadata.get("target_route")
        )
        return self._canonical_route_id(route)

    def _matching_hard_rule(self, text: str) -> tuple[str, str] | None:
        lowered = text.lower()
        for hard_rule in self.settings.hard_rules:
            for keyword in hard_rule.keywords:
                if keyword.lower() in lowered:
                    return hard_rule.route_id, keyword
        return None

    def _target_model_for_route(self, route_id: str) -> str:
        target_model = self.settings.routes[route_id].target_model
        if target_model is None:
            return route_id
        return target_model

    async def _ensure_route_vectors(self) -> None:
        if self._route_vectors is not None:
            return
        texts: list[str] = []
        offsets: list[tuple[str, int, int]] = []
        cursor = 0
        for route, spec in self.settings.routes.items():
            start = cursor
            texts.extend(spec.utterances)
            cursor += len(spec.utterances)
            offsets.append((route, start, cursor))

        vectors = await self.embedding_client.embed(texts) if texts else []
        self._route_vectors = {
            route: vectors[start:end] for route, start, end in offsets
        }


def latest_user_text(messages: Any) -> str:
    if not isinstance(messages, list):
        return ""

    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("role") != "user":
            continue

        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if not isinstance(part, dict) or part.get("type") != "text":
                    continue
                text = part.get("text")
                if isinstance(text, str) and text:
                    parts.append(text)
            return "\n".join(parts)
        return ""
    return ""


def looks_like_agent_instruction_boilerplate(text: str) -> bool:
    if not text:
        return False

    lowered = text.lower()
    hits = sum(
        1 for marker in AGENT_INSTRUCTION_BOILERPLATE_MARKERS if marker in lowered
    )
    return hits >= 2


def cosine_similarity(left: list[float], right: list[float]) -> float:
    left_array = np.asarray(left, dtype=np.float32)
    right_array = np.asarray(right, dtype=np.float32)
    denominator = float(np.linalg.norm(left_array) * np.linalg.norm(right_array))
    if denominator == 0.0:
        return 0.0
    return float(np.dot(left_array, right_array) / denominator)
