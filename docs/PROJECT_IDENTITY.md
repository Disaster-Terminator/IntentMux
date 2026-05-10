# Project Identity

## Product Name

```text
IntentMux
```

IntentMux is a lightweight, auditable intent-routing sidecar for LiteLLM and
OpenAI-compatible model gateways.

## Boundary

IntentMux is not a model provider and does not replace LiteLLM. It selects a
product-level `route_id` from request intent, then resolves that route to the
deployment-specific LiteLLM `target_model`.

```text
request intent -> route_id -> target_model -> LiteLLM model group
```

## Naming Contract

- Product name: `IntentMux`
- Python package metadata: `intentmux`
- Runtime module namespace: `router`
- Default LiteLLM entry model: `semantic-router`
- Default container and compose service name: `intentmux`
- Default container image tag for local builds: `intentmux:local`

The product name and the LiteLLM entry model intentionally differ. `IntentMux`
is the project identity; `semantic-router` is the opt-in model name that lets
existing LiteLLM clients route traffic with a minimal configuration change.

## Repository Metadata

Recommended repository title:

```text
IntentMux
```

Recommended description:

```text
Lightweight, auditable intent router for LiteLLM and OpenAI-compatible model gateways.
```

Recommended topics:

```text
llm-gateway
litellm
openai-compatible
model-routing
intent-routing
semantic-routing
agent-infra
observability
```
