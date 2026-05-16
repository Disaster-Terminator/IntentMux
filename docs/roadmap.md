# Roadmap

## Long-Term Operational Goal

Make IntentMux a lightweight local AI gateway that can act as an
OpenAI-compatible `base_url` with canonical `auto` / `lite` / `deep` entries,
while preserving the existing LiteLLM `semantic-router` sidecar deployment mode
for production compatibility.

Current operating target:

- every routed request emits one structured `route_complete` or `route_error`
  event without prompt or bearer-token leakage
- upstream disconnects and HTTP `5xx` statuses return a controlled `502` and
  are visible in route-log summaries
- runtime config validation prevents recursive entry-model targets while
  allowing product route ids `lite` / `deep` to map to deployment-specific
  target models
- `/v1/models` advertises only canonical synthetic entries: `auto`, `lite`, and
  `deep`; legacy `semantic-router`, `fast`, `strong`, and local target model
  names remain accepted or configured where needed but are not advertised
- degraded embedding availability is explicit: `/ready` returns `503`, routed
  chat requests fall back to `fallback_route_id` with
  `reason=embedding_error`, and route summaries count route ids, targets, and
  reasons for review
- health-check noise stays out of default logs
- production readiness is verified by unit tests, route evals, sidecar preflight,
  LiteLLM-entry E2E, and recent-log summaries

Next hardening targets:

- strict cross-layer correlation for LiteLLM model-entry requests; current
  LiteLLM entry mode does not forward client request IDs to the sidecar, while
  the sidecar now records `request_id_source` and injects its final
  `x-request-id` upstream
- explicit budget thresholds for `route_error` rates and degraded route reasons
  such as `embedding_error` via `scripts/check_route_error_budget.py`
- lifecycle coupling design for sidecar readiness and LiteLLM restart behavior;
  current `/ready` reports layered health while `/health` remains local liveness
- route-bank refresh workflow from real, redacted production examples using
  `scripts/import_review_samples.py`
- route quality review through `/v1/semantic-router/decision`, which returns
  the would-route decision without forwarding to LiteLLM or a model backend
- agent workload routing policy for tool-call and code-editing frameworks,
  including when callers should use `model=deep` or `metadata.route_id=deep`
- public-readiness work after the configurable route abstraction and
  observability contract have both been audited; the current repository should
  not be treated as public-release frozen

Product boundary:

- IntentMux owns OpenAI-compatible gateway behavior, entry-model semantics,
  routing decisions, request IDs, streaming pass-through, error classes, and
  privacy-safe logs.
- IntentMux does not replace LiteLLM provider routing, provider fallback,
  provider credentials, virtual keys, budgets, or model pools.
- LiteLLM remains the recommended upstream and the recommended compatibility
  layer for existing sidecar deployments.

## Lifecycle Management

The gateway is a separate component, not an internal LiteLLM module. It may run
in the same Docker Compose project for operational convenience, but its
repository, image, config, audit logs, and secrets boundary stay separate from
the LiteLLM mount directory.

Future direction: keep gateway-mode lifecycle independent while making the
LiteLLM sidecar compatibility lifecycle explicit. A good design should answer
these questions before implementation:

- Should router startup depend on LiteLLM health, service start, or a successful
  authenticated `/v1/models` probe?
- Should router restart when LiteLLM restarts, or only retry upstream calls?
- Should clients use IntentMux `:4001` directly in gateway mode, or keep using
  LiteLLM `:4000` with legacy `semantic-router` in sidecar mode?
- Should embedding degraded fallback remain fail-open for all routed requests,
  or should selected high-risk categories fail closed in the future?

This is intentionally not implemented yet. The current standard is a sibling
Compose service with its own health check and explicit upstream URLs.

## Semantic Assets

The route bank should be built from mature datasets plus redacted production
review samples, not from hand-written keyword expansion or self-generated
semantic corpora. The first production-grade milestone is:

- source manifest with auditable dataset names and filters
- reproducible small-sample route bank generation
- generated utterance records that retain source names
- eval cases expanded from the generated bank plus local ambiguous examples
- no runtime dependency on Hugging Face tooling
