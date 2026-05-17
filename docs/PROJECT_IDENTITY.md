# Project Identity

## Product Name

```text
IntentMux
```

IntentMux is a lightweight OpenAI-compatible routing gateway that routes
requests between `lite` and `deep` model tiers with auditable decisions. It can
run independently or as a LiteLLM-first sidecar behind an existing LiteLLM entry
point.

## Boundary

IntentMux is not a model provider and does not require LiteLLM to run. It owns
OpenAI-compatible gateway protocol, entry-model semantics, route decisions, and
privacy-safe route audit logs. The upstream can be LiteLLM or any
OpenAI-compatible service. In LiteLLM-first deployments, LiteLLM remains the
recommended layer for provider routing, provider fallback, provider
credentials, virtual keys, budgets, and model pools.

```text
model=auto -> route_id(lite/deep) -> target_model -> OpenAI-compatible upstream
```

## Naming Contract

- Product name: `IntentMux`
- Python package metadata: `intentmux`
- Runtime module namespace: `router`
- Canonical public entry models: `auto`, `lite`, `deep`
- LiteLLM sidecar entry name: `semantic-router`
- Historical internal route names have been migrated to `lite` / `deep`.
- Default container and compose service name: `intentmux`
- Default container image tag for local builds: `intentmux:local`

The product name and entry models intentionally differ. `IntentMux` is the
project identity. `auto`, `lite`, and `deep` are the canonical public model
entries. `semantic-router` is the LiteLLM sidecar entry name for LiteLLM-first
deployments; it is a compatibility entry name, not a second-class deployment
mode.

`/v1/models` should advertise only `auto`, `lite`, and `deep`. It should not
advertise deployment-specific upstream
model group names.

## Repository Metadata

Recommended repository title:

```text
IntentMux
```

Recommended description:

```text
Lightweight OpenAI-compatible `lite` / `deep` routing gateway with first-class LiteLLM sidecar support.
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
