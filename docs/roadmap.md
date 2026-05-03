# Roadmap

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

