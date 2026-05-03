# Gateway Semantic Router Design

## Goal

Build a lightweight Chinese routing sidecar in `/home/raystorm/gateway/gateway-semantic-router` and keep the existing LiteLLM Docker gateway on `127.0.0.1:4000` unchanged.

## Verified Local Facts

- LM Studio serves OpenAI-compatible embeddings at `http://127.0.0.1:1234/v1/embeddings`.
- The available embedding model includes `text-embedding-jina-embeddings-v5-text-small-retrieval@q8_0`.
- LiteLLM listens on `127.0.0.1:4000` and exposes `cheap-router`, `pro-router`, `free-probe-router`, and `smart-router`.
- `gh` is authenticated as `Disaster-Terminator` and can create private repositories.
- The router repository is separate from `/home/raystorm/gateway/litellm`; the LiteLLM mount directory and its secrets are not part of this git repository.

## Architecture

The sidecar exposes `/v1/chat/completions` and `/health`. It accepts OpenAI-compatible chat completion JSON, forwards non-`smart-router` requests unchanged, and routes only `model=smart-router` by rewriting `model` to a LiteLLM group.

Routing uses three layers:

1. Explicit route metadata or headers, when present.
2. Strong Chinese/technical hard rules for high-risk tasks that must go to `pro-router`.
3. Embedding similarity against route utterances in `config/routes.yaml`.

If embedding fails or the score is below threshold, the sidecar falls back to `cheap-router`.

## Components

- `router/config.py`: loads settings and route definitions from YAML and environment.
- `router/routing.py`: extracts user text, applies hard rules, computes route scores, and returns a routing decision.
- `router/embedding.py`: calls the OpenAI-compatible embedding endpoint.
- `router/proxy.py`: forwards requests to LiteLLM and preserves streaming bytes.
- `router/app.py`: FastAPI application and request handling.
- `tests/`: unit tests, proxy tests, and eval cases.

## Testing

Tests must cover route pass-through, hard-rule pro routing, embedding-based route selection, embedding failure fallback, and non-streaming proxy behavior. A YAML eval set covers Chinese cheap/probe/pro routing examples and can be run locally without hitting paid model providers when embedding is mocked.
