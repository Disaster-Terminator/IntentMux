# Configurable Route Abstraction Design

## Problem

The current router prototype binds product-level route categories to this
machine's LiteLLM model group names:

- `cheap-router`
- `pro-router`
- `free-probe-router`

Those names are valid local deployment targets, but they must not be the public
product contract. Today they leak into runtime validation, hard-rule routing,
eval expectations, review-sample import, E2E probes, logs, README language, and
roadmap language. If this shape is frozen, future log contracts and public docs
will describe one local LiteLLM deployment rather than a reusable routing
sidecar.

## Product Boundary

`gateway-semantic-router` should be a lightweight, local-first,
OpenAI/LiteLLM-compatible routing sidecar. It should expose one stable entry
model, inspect matching requests, choose a configured route, and rewrite the
request to that route's configured target model.

It should not compete with mature upstream routers as a broad model-management
platform. Its differentiators are local deployment, low-intrusion LiteLLM
integration, auditable route decisions, redacted eval/review workflows, and a
small configuration surface.

## Core Terms

- `entry_model`: The model name clients call to opt into the sidecar, for
  example `semantic-router`.
- `route_id`: A product-level route category chosen by the sidecar, for example
  `fast`, `strong`, `experimental`, or any user-defined id.
- `target_model`: The deployment-level upstream model name to send to LiteLLM,
  for example a LiteLLM model group or provider model. Local names such as
  `cheap-router` are valid here only as examples.
- `policy_id`: The policy family that selected the route, such as
  `hard_rule`, `embedding`, `low_confidence`, `embedding_error`, `explicit`, or
  `passthrough`.
- `fallback_route_id`: A configured `route_id` to use when semantic selection
  is unavailable or too ambiguous.

## Configuration Direction

Routes should be declared as user-defined ids with explicit targets:

```yaml
entry_model: semantic-router
fallback_route_id: fast
threshold: 0.55
margin: 0.04

hard_rules:
  - route_id: strong
    keywords:
      - debug
      - PR
      - 线上

routes:
  fast:
    target_model: cheap-router
    description: Low-risk, fast, inexpensive local target.
    utterances:
      - 帮我润色这句话

  strong:
    target_model: pro-router
    description: Complex coding and high-risk analysis target.
    utterances:
      - 这个线上 bug 为什么偶发
```

The default preset can use a two-route mental model (`fast` and `strong`)
because that matches common local-agent needs. The product must still support
any number of user-defined routes. An optional `experimental` route can remain
in local examples, but it is not part of the public contract. Example names
such as `cheap-router`, `pro-router`, and `free-probe-router` are
deployment-level `target_model` values only.

## Runtime Contract

`RoutingDecision` should carry both route and target information:

- `route_id`
- `target_model`
- `policy_id`
- `reason`
- `rewrite`
- `source_model`
- `score`
- `second_score`

Hard rules must select a configured `route_id`, then resolve that route to
`target_model`. They must never return a hardcoded local LiteLLM group name.

Routes with empty `utterances` are allowed as hard-rule-only routes. Semantic
embedding ranking must safely skip empty-utterance routes. If no route has any
semantic utterances to score, routing must deterministically return
`fallback_route_id` with `policy_id=low_confidence` (not `embedding_error`).

The router must retain recursive-routing protection:

- The entry model must not be a target model.
- The fallback route must exist.
- Every route must have a target model.
- Explicit route requests must reference a configured route id.

## Logging Contract

Structured route logs should record both product-level and deployment-level
fields:

- `route_id`
- `target_model`
- `policy_id`
- `reason`
- `request_id`
- `request_id_source`
- `source_model`
- `rewrite`
- `stream`
- `upstream_status` when available
- `score` and `second_score` when semantic scoring ran
- `duration_ms`
- `error_type` for route errors

This lets operators analyze route quality by stable `route_id` while still
debugging deployment failures by `target_model`.

Prompt text, bearer tokens, LiteLLM secrets, and raw production config must not
be logged or committed.

## Eval And Review Contract

Eval cases and redacted production-review samples should expect `route_id`, not
deployment target names. `target_model` is an output derived from configuration,
so it can be included in JSON diagnostics but should not define route quality.

Old local target names may remain in checked-in sample config and fixtures only
when clearly labeled as example LiteLLM targets.

## Public Readiness

The project is not ready for public release while this abstraction is mixed.
Public readiness, repository visibility changes, and license polishing should
resume after configurable route abstraction, observability contract, and
redacted eval workflow audits confirm the same route-id contract across logs,
evals, and docs.

## Non-Goals For This Phase

- Do not redesign LiteLLM or modify `/home/raystorm/gateway/litellm`.
- Do not build a full upstream model registry.
- Do not add provider-specific model management.
- Do not publish the repository or add public-release claims in this phase.
