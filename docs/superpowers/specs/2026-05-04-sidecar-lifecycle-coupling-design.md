# Semantic Router Sidecar Lifecycle-Coupling Design Note

## Status

Design-only note. No lifecycle-coupling behavior is implemented by this document.

## Purpose

Define an explicit lifecycle-coupling strategy for the semantic-router sidecar so future implementation PRs do not invent behavior ad hoc, while preserving the sidecar boundary from LiteLLM.

## Current Lifecycle Model

- **Sibling sidecar**: semantic-router runs as a peer service next to LiteLLM, not as an internal LiteLLM component.
- **Boundary separation**: sidecar and LiteLLM remain separate in repository, image, configuration, and secret ownership.
- **`/health` = local liveness**: sidecar process-level health only (no downstream dependency checks).
- **`/ready` = layered readiness**: sidecar readiness may include local startup and dependency checks needed for routing quality.
- **Docker health remains local liveness**: healthcheck intentionally avoids dependency gating to reduce restart-loop risk.

## Problem Statement

We need a clear policy for lifecycle behavior when:

1. **LiteLLM restarts** happen while sidecar remains up.
2. **Sidecar readiness changes** due to dependency availability or warmup states.
3. **Embedding degraded mode** is active (fallback behavior available but routing quality reduced).
4. **Client entrypoint ambiguity** exists between targeting LiteLLM directly on `:4000` versus the sidecar on `:4001`.

Without a design contract, implementation may introduce implicit coupling, inconsistent failure behavior, or risky restart automation.

## Non-Goals

- No secret sharing between LiteLLM and semantic-router.
- No mounting LiteLLM runtime config into this repository.
- No broad Docker Compose restart loops that bounce multiple services automatically on transient dependency failures.

## Option Space

### 1) Keep Current Decoupled Sidecar

- Keep current liveness/readiness model.
- Do not add lifecycle coupling signals or restart policy changes.
- Rely on operators and client routing choice for resilience.

**Pros**: simplest, preserves boundaries, low blast radius.
**Cons**: unclear operational guidance during degraded periods.

### 2) Add Readiness Gating Only

- Keep `/health` local.
- Expand `/ready` contract to explicitly represent:
  - upstream LiteLLM reachability,
  - embedding availability,
  - degraded-mode state.
- Keep restart behavior decoupled.

**Pros**: better observability and traffic gating without restart loops.
**Cons**: requires consumers/operators to honor readiness semantics.

### 3) Add Explicit Operator Preflight Gate

- Define a preflight checklist or command gate for production promotion.
- Require successful preflight, E2E checks, and budget guardrails before routing production traffic through sidecar.
- Can coexist with Option 2.

**Pros**: strong operational discipline; avoids hidden automation coupling.
**Cons**: manual/operator workflow overhead.

### 4) Add Tighter Restart Coupling

- Tie sidecar lifecycle to LiteLLM restart events (directly or via orchestrator policy).
- Potentially restart sidecar when LiteLLM flaps or changes state.

**Pros**: may simplify some stale-connection scenarios.
**Cons**: higher risk of cascading restart loops, reduced fault isolation, and boundary erosion.

## Recommended Near-Term Direction

Adopt **Option 2 + Option 3**, and defer Option 4.

- Prefer readiness/preflight gating over automatic restart coupling.
- Keep `/health` local liveness only.
- Keep `/ready` layered and explicit about degraded mode.
- Make production promotion depend on:
  - preflight gate pass,
  - end-to-end gateway validation pass,
  - budget/safety gate pass.

This keeps the sidecar independently operable while making traffic-management decisions explicit and auditable.

## Risks

- Teams may still send traffic to `:4000` and bypass sidecar policy unintentionally.
- Readiness signals may be ignored by clients or deployment tooling.
- Degraded mode semantics may be misunderstood as hard-failure or as fully acceptable quality.
- Preflight checks can drift from real runtime failure modes if not maintained.

## Open Questions

1. Should degraded embedding mode report `ready=true` with structured warnings, or `ready=false` for strict gating?
2. What is the canonical production client entrypoint (`:4001` preferred?) and migration strategy for existing `:4000` clients?
3. Which readiness consumers are authoritative (orchestrator, ingress, synthetic checks, operators)?
4. What timeout/retry windows distinguish transient LiteLLM restarts from sustained unready states?
5. What minimum E2E and budget checks are required for promotion in each environment?

## Future Implementation PR Acceptance Criteria

A future implementation PR is acceptable only if it satisfies all of the following:

1. **Design fidelity**: documents and code state that sidecar boundary remains separate from LiteLLM (repo/image/config/secrets).
2. **No hidden coupling**: does not introduce automatic broad restart-loop behavior between services.
3. **Health contract preserved**: `/health` remains local liveness only.
4. **Readiness contract explicit**: `/ready` clearly represents layered readiness, including degraded embedding semantics.
5. **Client guidance delivered**: operator docs state when to target `:4001` sidecar versus direct `:4000` LiteLLM.
6. **Preflight gate defined**: production promotion requires explicit preflight + E2E + budget gate checks.
7. **Test coverage**: includes deterministic tests for LiteLLM restart scenarios, readiness transitions, and degraded-mode signaling.
8. **No false claim**: release notes/changelog do not claim full lifecycle coupling automation if only readiness/preflight gating is implemented.

