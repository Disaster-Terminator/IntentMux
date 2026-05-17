# Project Control

This is IntentMux's current control surface. Use it before older plans,
roadmaps, or research notes.

## Vision

IntentMux is a lightweight OpenAI-compatible `lite` / `deep` router. It should
improve as it is used, but "learnable" means evidence-driven operations, not a
large labeling or training project.

```text
runtime logs
  -> scripts select candidates and compute baselines
  -> external AI reviewer reads candidate packets and reports uncertainty
  -> humans audit only policy, privacy, and unclear cases
  -> accepted evidence becomes redacted regression cases or route-bank assets
  -> before/after quality reports gate policy changes
```

IntentMux does not run the AI reviewer inside the routing runtime. It exposes a
learning interface: packet generation, schema validation, summaries, and import
gates. Local automation can connect that interface to any AI runner.

## Boundaries

Keep in scope:

- OpenAI-compatible proxying, route decisions, and privacy-safe audit logs.
- Two product tiers: `lite` for low-risk/cost-first traffic, `deep` for higher
  capability or higher risk.
- LiteLLM-first sidecar support without replacing LiteLLM provider routing,
  keys, budgets, fallback, or model pools.
- Offline route-bank and eval-asset generation.
- External AI-first review with script guardrails and human audit.

Keep out of scope:

- trained router models;
- vector database runtime dependencies;
- large manual labeling campaigns;
- self-generated semantic corpora;
- bulk-translated benchmark corpora presented as Chinese route quality;
- treating AI-generated labels as truth without validation.
- runtime self-modification of thresholds, hard rules, or route banks.

## Data Policy

Use mature public data only when it naturally maps to `lite` / `deep`.

- MASSIVE Chinese general utterances can support `lite` route-bank examples.
- SWE-bench / MBPP / HumanEval-like coding tasks can support `deep` examples.
- C-Eval, CMMLU, LongBench, DataCLUE, SuperCLUE-Code3, and similar benchmarks
  are methodology or local-only evidence unless a route label is natural and
  reviewable.
- Redacted production review samples can become regression cases after AI
  review, human audit when needed, and schema/privacy validation.

## Current State

Implemented:

- `auto` / `lite` / `deep` route semantics and `semantic-router` sidecar entry;
- metadata-only route audit logs and optional local prompt review logs;
- health reports, route budgets, review-candidate selection;
- smoke evals and baseline comparison: `current-router`, `always-lite`,
  `always-deep`, `hard-rule-only`;
- quality report generation from eval JSON and route summaries.

Not closed:

- daily health does not yet emit the full quality report plus AI-review packet;
- AI review is not yet a generic repo-level workflow;
- accepted findings are not routinely imported into redacted regression cases;
- threshold and margin are not calibrated from enough representative evidence;
- full-history logs still include legacy `fast` / `strong`, so current policy
  analysis must prefer current-day or post-migration logs.

## Active Work Order

Do these in order. Do not start a new architecture direction until the current
item is closed.

1. Keep this control surface, evidence status, log-driven loop, and plan
   registry consistent.
2. Add a generic local-only AI review packet. It must not require RayStorm,
   Hermes, Retinue, or OpenCode.
3. Wire daily quality artifacts into health: evals, baselines, route summary,
   review candidates, and AI-review packet paths.
4. Add a learning import gate for accepted redacted cases.
5. Tune route bank, hard rules, threshold, or margin only after reports show a
   repeated actionable pattern.

## Stop Conditions

Stop and discuss before work that would:

- require bulk manual labeling;
- put raw prompts or private logs in git;
- hard-code local RayStorm paths into public files;
- treat benchmark categories as route truth without review;
- change production routing policy without before/after evidence;
- add or expand docs without reducing ambiguity.

## References

- Semantic Router thresholds:
  https://docs.aurelio.ai/semantic-router/user-guide/features/threshold-optimization
- RouteLLM:
  https://sky.cs.berkeley.edu/project/routellm/
- RouterBench:
  https://arxiv.org/abs/2403.12031
