# Roadmap

## Long-Term Operational Goal

Make `semantic-router` a low-intrusion LiteLLM model-entry sidecar that can stay
in production traffic with auditable routing decisions, bounded failure modes,
and repeatable E2E checks.

Current operating target:

- every routed request emits one structured `route_complete` or `route_error`
  event without prompt or bearer-token leakage
- upstream disconnects and HTTP `5xx` statuses return a controlled `502` and
  are visible in route-log summaries
- runtime config validation prevents recursive `semantic-router` targets while
  allowing user-defined route ids mapped to deployment-specific target models
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
- public-readiness work after the configurable route abstraction and
  observability contract have both been audited; the current repository should
  not be treated as public-release frozen

## Lifecycle Management

The router is a third-party sidecar, not an internal LiteLLM component. It may
run in the same Docker Compose project for operational convenience, but its
repository, image, config, and secrets boundary stay separate from the LiteLLM
mount directory.

Future direction: bind the router sidecar lifecycle to the LiteLLM service
itself, not to the broader compose group. A good design should answer these
questions before implementation:

- Should router startup depend on LiteLLM health, service start, or a successful
  authenticated `/v1/models` probe?
- Should router restart when LiteLLM restarts, or only retry upstream calls?
- Should clients switch to `:4001` only after router and LiteLLM are both ready?
- Should embedding degraded fallback remain fail-open for all routed requests,
  or should selected high-risk categories fail closed in the future?

This is intentionally not implemented yet. The current standard is a sibling
Compose service with its own health check and explicit upstream URLs.

## Semantic Assets

The route bank should be built from mature datasets plus local logs, not from
hand-written keyword expansion. The first production-grade milestone is:

- source manifest with auditable dataset names and filters
- reproducible small-sample route bank generation
- generated utterance records that retain source names
- eval cases expanded from the generated bank plus local ambiguous examples
- no runtime dependency on Hugging Face tooling
