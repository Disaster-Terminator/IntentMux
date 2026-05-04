# Lifecycle Coupling Design Note (Semantic Router Sidecar)

## Status

Design only. This document does **not** implement lifecycle coupling behavior.

## Purpose

Define a clear lifecycle-coupling direction for future implementation work so
readiness, restart, and production-promotion behavior are added intentionally
rather than ad hoc.

## Current Lifecycle Model

- The semantic router runs as a **sibling sidecar** to LiteLLM.
- The router remains a **separate boundary** from LiteLLM for repo, image,
  runtime config, and secrets.
- `GET /health` is **local liveness** only (process-local health).
- `GET /ready` is **layered readiness** (includes external dependencies and
  degraded states).
- Docker health check intentionally uses local liveness semantics to avoid broad
  restart loops caused by transient upstream or embedding outages.

## Problem Statement

Operators need a defined policy for these lifecycle interactions:

1. **LiteLLM restarts**: what should the sidecar do when LiteLLM restarts or is
   briefly unavailable?
2. **Sidecar readiness**: when is it safe to send production traffic to the
   sidecar entrypoint?
3. **Embedding degraded mode**: when embeddings are degraded, should readiness
   block promotion while routed traffic remains fail-open via fallback?
4. **Client target selection**: should clients call LiteLLM model entry (`:4000`)
   or sidecar entry (`:4001`) at each rollout stage?

Without explicit design, operators may introduce accidental coupling,
secret/config boundary erosion, or unstable restart behavior.

## Non-Goals

- No secret sharing between LiteLLM and sidecar.
- No mounting LiteLLM config into this repository or sidecar container.
- No broad Docker Compose restart coupling (no group-wide restart loops).
- No claim that restart coupling is already implemented.

## Options

### Option 1: Keep current decoupled sidecar

- Keep independent container lifecycle.
- Keep local `/health` and layered `/ready` semantics.
- Rely on retry/fallback behavior and operator procedures for rollout.

**Pros**: simplest, stable boundary, minimal risk of restart storms.  
**Cons**: operator discipline required; rollout safety depends on manual checks.

### Option 2: Add readiness gating only

- Preserve independent restart lifecycle.
- Add explicit traffic/promotion gates requiring sidecar + upstream readiness.
- Keep Docker health check local (`/health`), not layered.

**Pros**: improves safety with low coupling.  
**Cons**: does not automatically re-align processes after restarts.

### Option 3: Add explicit operator preflight gate

- Require a preflight command/checklist before promotion to `:4001`.
- Preflight validates sidecar readiness, LiteLLM reachability, E2E path, and
  route-error budget/degraded counters.
- Promotion remains a deliberate operator action.

**Pros**: auditable and controllable; avoids automated restart loops.  
**Cons**: slower rollout path; requires operational runbook enforcement.

### Option 4: Add tighter restart coupling

- Couple sidecar restart behavior directly to LiteLLM restart events/health.
- Potentially coordinate startup/restart ordering beyond readiness checks.

**Pros**: may reduce manual intervention after upstream restart events.  
**Cons**: highest risk of coupling drift, restart cascades, and boundary
complexity.

## Recommended Near-Term Direction

Adopt **Option 2 + Option 3**, and defer Option 4.

- Prefer readiness + preflight gating over automatic restart coupling.
- Keep `/health` local liveness.
- Keep `/ready` layered readiness.
- Make production promotion to sidecar model entry depend on:
  1. successful preflight,
  2. passing LiteLLM-entry + sidecar-entry E2E checks,
  3. route-error/degraded-reason budget gate.

## Risks and Open Questions

- Which layered checks in `/ready` should be hard-fail vs informational?
- Should embedding degraded mode block promotion universally, or only for
  selected high-risk routes?
- How long should readiness failures persist before operator intervention is
  required?
- What is the rollback trigger when route-error budget is exceeded after
  promotion?
- Should preflight enforce a minimum observation window over recent route logs?

## Acceptance Criteria for a Future Implementation PR

A future PR that implements lifecycle coupling controls is acceptable only if it:

1. Preserves sidecar boundary (separate repo/image/config/secrets).
2. Keeps `/health` as local liveness and does not repurpose it as layered
   readiness.
3. Keeps `/ready` as layered readiness and documents each dependency signal.
4. Adds explicit preflight + promotion gating for sidecar entry (`:4001`) with
   reproducible commands.
5. Requires E2E verification for both LiteLLM entry (`:4000`) and sidecar entry
   (`:4001`) before promotion.
6. Enforces a defined route-error/degraded budget gate in promotion checks.
7. Avoids broad compose-wide automatic restart loops.
8. Clearly documents restart behavior when LiteLLM restarts (retry, backoff,
   and operator expectations).
9. Includes runbook updates describing promotion, rollback, and degraded-mode
   handling.
10. States explicitly that lifecycle coupling remains limited to readiness and
    operator gating unless a later ADR approves tighter restart coupling.
