# Project Identity

## Product Name

```text
IntentMux
```

IntentMux is a lightweight local AI gateway that routes OpenAI-compatible
requests between `lite` and `deep` model tiers with auditable decisions, while
preserving LiteLLM sidecar compatibility.

## Boundary

IntentMux is not a model provider and does not replace LiteLLM. It owns
OpenAI-compatible gateway protocol, entry-model semantics, route decisions, and
privacy-safe route audit logs. LiteLLM remains the recommended upstream for
provider routing, provider fallback, provider credentials, virtual keys,
budgets, and model pools.

```text
model=auto -> route_id(lite/deep) -> target_model -> OpenAI-compatible upstream
```

## Naming Contract

- Product name: `IntentMux`
- Python package metadata: `intentmux`
- Runtime module namespace: `router`
- Canonical public entry models: `auto`, `lite`, `deep`
- Legacy LiteLLM sidecar entry alias: `semantic-router`
- Legacy route aliases: `fast` -> `lite`, `strong` -> `deep`
- Default container and compose service name: `intentmux`
- Default container image tag for local builds: `intentmux:local`

The product name and entry models intentionally differ. `IntentMux` is the
project identity. `auto`, `lite`, and `deep` are the canonical public model
entries. `semantic-router` is retained as a backward-compatible LiteLLM sidecar
entry alias for existing deployments.

`/v1/models` should advertise only `auto`, `lite`, and `deep`. It should not
advertise `semantic-router`, `fast`, `strong`, or deployment-specific upstream
model group names.

## Repository Metadata

Recommended repository title:

```text
IntentMux
```

Recommended description:

```text
Lightweight local AI gateway for OpenAI-compatible `lite` / `deep` routing with LiteLLM sidecar compatibility.
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
