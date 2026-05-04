# Roadmap

## Long-Term Operational Goal

Make `semantic-router` a low-intrusion LiteLLM model-entry sidecar that can stay
in production traffic with auditable routing decisions, bounded failure modes,
and repeatable E2E checks.

Current operating target:

- every routed request emits one structured `route_complete` or `route_error`
  event without prompt or bearer-token leakage
- upstream disconnects return a controlled `502` and are visible in route-log
  summaries
- health-check noise stays out of default logs
- production readiness is verified by unit tests, route evals, sidecar preflight,
  LiteLLM-entry E2E, and recent-log summaries

Next hardening targets:

- strict cross-layer correlation for LiteLLM model-entry requests; current
  LiteLLM entry mode does not forward client request IDs to the sidecar
- an explicit error-budget threshold for `route_error` rates by target model
- lifecycle coupling design for sidecar readiness and LiteLLM restart behavior
- route-bank refresh workflow from real, redacted production examples

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
- How should degraded embedding availability affect readiness versus routing
  fallback?

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
