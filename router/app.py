from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import Response

from router.config import RouterSettings, load_settings
from router.embedding import OpenAIEmbeddingClient
from router.proxy import LiteLLMProxy
from router.routing import Router


logger = logging.getLogger("gateway_semantic_router")


def create_app(
    settings: RouterSettings | None = None,
    router: Router | None = None,
    proxy: LiteLLMProxy | None = None,
) -> FastAPI:
    if settings is None:
        settings = load_settings()
    if router is None:
        router = Router(
            settings,
            OpenAIEmbeddingClient(settings.embedding_url, settings.embedding_model),
        )
    if proxy is None:
        proxy = LiteLLMProxy(settings.litellm_base_url)

    app = FastAPI(title="Gateway Semantic Router")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> Response:
        payload: dict[str, Any] = await request.json()
        decision = await router.decide(payload)
        forwarded_payload = dict(payload)
        forwarded_payload["model"] = decision.target_model
        logger.info(
            "route source=%s target=%s reason=%s score=%s second_score=%s",
            decision.source_model,
            decision.target_model,
            decision.reason,
            decision.score,
            decision.second_score,
        )
        upstream = await proxy.forward_chat(forwarded_payload, dict(request.headers))
        headers = dict(upstream.headers)
        headers["x-router-target-model"] = decision.target_model
        headers["x-router-reason"] = quote(decision.reason, safe=":._-")
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=headers,
            media_type=headers.get("content-type"),
        )

    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = load_settings()
    uvicorn.run(
        create_app(settings=settings),
        host=settings.listen_host,
        port=settings.listen_port,
    )


if __name__ == "__main__":
    main()
