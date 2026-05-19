from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
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
    match_source: str | None = None
    match_index: int | None = None
    match_text_sha256: str | None = None


class Router:
    def __init__(self, settings: RouterSettings, embedding_client: EmbeddingClient):
        self.settings = settings
        self.embedding_client = embedding_client
        self._route_vectors: dict[str, list[RouteVector]] | None = None
        self._aurelio_router: Any | None = None

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
            route_matches = self._rank_route_matches(query_vector)
        except Exception:
            return RoutingDecision(
                route_id=self.settings.fallback_route_id,
                target_model=self._target_model_for_route(self.settings.fallback_route_id),
                source_model=source_model,
                reason="embedding_error",
                policy_id="embedding_error",
                rewrite=True,
            )

        if not route_matches:
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

        ranked = sorted(route_matches.items(), key=lambda item: item[1].score, reverse=True)
        best_route, best_match = ranked[0]
        best_score = best_match.score
        second_score = ranked[1][1].score if len(ranked) > 1 else 0.0
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
            match_source=best_match.source,
            match_index=best_match.index,
            match_text_sha256=best_match.text_sha256,
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
        entries: list[RouteCorpusEntry] = []
        for route, spec in self.settings.routes.items():
            for index, text in enumerate(spec.utterances):
                entries.append(
                    RouteCorpusEntry(
                        route_id=route,
                        text=text,
                        source=spec.utterance_sources.get(text),
                        index=index,
                        text_sha256=sha256_text(text),
                    )
                )

        cached_vectors = self._load_route_vector_cache(entries)
        if cached_vectors is not None:
            self._route_vectors = cached_vectors
            return

        texts = [entry.text for entry in entries]
        vectors = await self.embedding_client.embed(texts) if texts else []
        route_vectors: dict[str, list[RouteVector]] = {
            route: [] for route in self.settings.routes
        }
        for entry, vector in zip(entries, vectors):
            route_vectors[entry.route_id].append(
                RouteVector(
                    vector=vector,
                    text=entry.text,
                    source=entry.source,
                    index=entry.index,
                    text_sha256=entry.text_sha256,
                )
            )
        self._route_vectors = route_vectors
        self._write_route_vector_cache(entries, vectors)

    def _load_route_vector_cache(
        self, entries: list["RouteCorpusEntry"]
    ) -> dict[str, list["RouteVector"]] | None:
        cache_path = self._route_embedding_cache_path()
        if cache_path is None:
            return None
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

        if (
            payload.get("version") != 1
            or payload.get("embedding_model") != self.settings.embedding_model
            or payload.get("route_bank_sha256") != route_bank_fingerprint(entries)
        ):
            return None

        items = payload.get("items")
        if not isinstance(items, list) or len(items) != len(entries):
            return None

        route_vectors: dict[str, list[RouteVector]] = {
            route: [] for route in self.settings.routes
        }
        for entry, item in zip(entries, items):
            if not isinstance(item, dict):
                return None
            vector = item.get("vector")
            if (
                item.get("route_id") != entry.route_id
                or item.get("source") != entry.source
                or item.get("index") != entry.index
                or item.get("text_sha256") != entry.text_sha256
                or not isinstance(vector, list)
            ):
                return None
            route_vectors[entry.route_id].append(
                RouteVector(
                    vector=vector,
                    text=entry.text,
                    source=entry.source,
                    index=entry.index,
                    text_sha256=entry.text_sha256,
                )
            )
        return route_vectors

    def _write_route_vector_cache(
        self, entries: list["RouteCorpusEntry"], vectors: list[list[float]]
    ) -> None:
        cache_path = self._route_embedding_cache_path()
        if cache_path is None or len(entries) != len(vectors):
            return
        payload = {
            "version": 1,
            "embedding_model": self.settings.embedding_model,
            "route_bank_sha256": route_bank_fingerprint(entries),
            "items": [
                {
                    "route_id": entry.route_id,
                    "source": entry.source,
                    "index": entry.index,
                    "text_sha256": entry.text_sha256,
                    "vector": vector,
                }
                for entry, vector in zip(entries, vectors)
            ],
        }
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = cache_path.with_name(f".{cache_path.name}.tmp")
            tmp_path.write_text(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            tmp_path.replace(cache_path)
        except OSError:
            return

    def _route_embedding_cache_path(self) -> Path | None:
        if (
            not self.settings.route_embedding_cache_enabled
            or not self.settings.route_embedding_cache_path
        ):
            return None
        return Path(self.settings.route_embedding_cache_path).expanduser()

    def _rank_route_matches(self, query_vector: list[float]) -> dict[str, "RouteMatch"]:
        if self._route_vectors is None:
            return {}
        if self.settings.route_kernel == "aurelio":
            return self._rank_route_matches_with_aurelio(query_vector)
        return self._rank_route_matches_basic(query_vector)

    def _rank_route_matches_basic(self, query_vector: list[float]) -> dict[str, "RouteMatch"]:
        if self._route_vectors is None:
            return {}
        route_matches = {}
        for route, vectors in self._route_vectors.items():
            if not vectors:
                continue
            route_matches[route] = max(
                (self._match_for_vector(query_vector, item) for item in vectors),
                key=lambda item: item.score,
            )
        return route_matches

    def _rank_route_matches_with_aurelio(
        self, query_vector: list[float]
    ) -> dict[str, "RouteMatch"]:
        if self._route_vectors is None:
            return {}
        router = self._ensure_aurelio_router()
        choices = router(vector=np.asarray(query_vector, dtype=np.float32), limit=2)
        if choices is None:
            return {}
        if not isinstance(choices, list):
            choices = [choices]

        route_matches: dict[str, RouteMatch] = {}
        for choice in choices:
            route_name = getattr(choice, "name", None)
            if not isinstance(route_name, str) or route_name not in self._route_vectors:
                continue
            score = getattr(choice, "similarity_score", None)
            if score is None:
                continue
            route_matches[route_name] = self._best_match_for_route(
                route_name,
                query_vector,
                score=float(score),
            )
        return route_matches

    def _ensure_aurelio_router(self) -> Any:
        if self._aurelio_router is not None:
            return self._aurelio_router
        if self._route_vectors is None:
            raise RuntimeError("route vectors must be initialized before aurelio router")

        try:
            from semantic_router import Route as AurelioRoute
            from semantic_router import SemanticRouter as AurelioSemanticRouter
            from semantic_router.encoders import DenseEncoder
            from semantic_router.index import LocalIndex
        except ImportError as exc:
            raise RuntimeError(
                "route_kernel=aurelio requires the optional upstream-router dependency group"
            ) from exc

        embeddings: list[list[float]] = []
        routes: list[str] = []
        utterances: list[str] = []
        metadata: list[dict[str, Any]] = []
        for route_id, vectors in self._route_vectors.items():
            for item in vectors:
                embeddings.append(item.vector)
                routes.append(route_id)
                utterances.append(item.text)
                metadata.append(
                    {
                        "source": item.source,
                        "index": item.index,
                        "text_sha256": item.text_sha256,
                    }
                )

        if not embeddings:
            raise RuntimeError("route_kernel=aurelio requires at least one route vector")

        dimensions = len(embeddings[0])

        class IntentMuxVectorOnlyEncoder(DenseEncoder):
            name: str = "intentmux-vector-only"

            def __call__(self, docs: list[Any]) -> list[list[float]]:
                return [[0.0] * dimensions for _ in docs]

        index = LocalIndex()
        index.add(
            embeddings=embeddings,
            routes=routes,
            utterances=utterances,
            metadata_list=metadata,
        )
        aurelio_routes = [
            AurelioRoute(name=route_id, utterances=[])
            for route_id in self.settings.routes
        ]
        self._aurelio_router = AurelioSemanticRouter(
            encoder=IntentMuxVectorOnlyEncoder(),
            index=index,
            routes=aurelio_routes,
            auto_sync=None,
        )
        return self._aurelio_router

    def _best_match_for_route(
        self, route_id: str, query_vector: list[float], *, score: float
    ) -> "RouteMatch":
        if self._route_vectors is None:
            raise RuntimeError("route vectors are not initialized")
        vectors = self._route_vectors.get(route_id) or []
        if not vectors:
            return RouteMatch(score=score, source=None, index=0, text_sha256="")
        basic_match = max(
            (self._match_for_vector(query_vector, item) for item in vectors),
            key=lambda item: item.score,
        )
        return RouteMatch(
            score=score,
            source=basic_match.source,
            index=basic_match.index,
            text_sha256=basic_match.text_sha256,
        )

    def _match_for_vector(
        self, query_vector: list[float], item: "RouteVector"
    ) -> "RouteMatch":
        return RouteMatch(
            score=cosine_similarity(query_vector, item.vector),
            source=item.source,
            index=item.index,
            text_sha256=item.text_sha256,
        )


@dataclass(frozen=True)
class RouteCorpusEntry:
    route_id: str
    text: str
    source: str | None
    index: int
    text_sha256: str


@dataclass(frozen=True)
class RouteVector:
    vector: list[float]
    text: str
    source: str | None
    index: int
    text_sha256: str


@dataclass(frozen=True)
class RouteMatch:
    score: float
    source: str | None
    index: int
    text_sha256: str


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def route_bank_fingerprint(entries: list[RouteCorpusEntry]) -> str:
    lines = [
        json.dumps(
            {
                "route_id": entry.route_id,
                "source": entry.source,
                "index": entry.index,
                "text_sha256": entry.text_sha256,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for entry in entries
    ]
    return sha256_text("\n".join(lines))


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
