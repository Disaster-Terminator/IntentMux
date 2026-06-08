# Project Control

This is IntentMux's current control surface. Use it before older plans,
roadmaps, or research notes.

## Vision

IntentMux is a lightweight OpenAI-compatible `lite` / `deep` router. It is
Chinese-first, not Chinese-only: Chinese production quality is the product
differentiator, while English routing data and mature English router practices
must keep the default router from falling behind the broader ecosystem.

IntentMux should improve as it is used, but "learnable" means evidence-driven
operations, not a large labeling or training project.

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

## Operating Model

Route behavior is frozen by default. Changes are driven by production logs and
calibration reports, not by intuition, benchmark labels alone, or oral
consensus.

- Route-bank, threshold, margin, and hard-rule changes require before/after
  quality evidence with baseline comparisons.
- Production runtime assets such as route banks, eval banks, logs, caches, and
  review files are untracked deployment artifacts. Commit public examples,
  schemas, manifests, and code instead.
- Prompt review logs are private. They are disabled by default, local-only when
  enabled, and must not be synced to git or attached to public reports.

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

## Default Routing Standard

The default router should be cost-first and promote only when there is evidence
that `deep` is needed.

Use this decision standard:

```text
explicit route
  -> high-precision hard escalation
  -> embedded route-bank similarity
  -> threshold and margin
  -> configured fallback when confidence is low
```

Quality changes must be judged by both routing quality and `deep` call rate.
Every route-bank, hard-rule, threshold, or margin change should compare against
`always-lite`, `always-deep`, and rule-only baselines.

## Data Policy

Use mature public data only when it naturally maps to `lite` / `deep`.

- Chinese general and short-task data can support `lite` route-bank examples.
- English and Chinese coding, debugging, security, and long-context data can
  support `deep` route-bank examples when the mapping is natural.
- C-Eval, CMMLU, LongBench, DataCLUE, SuperCLUE-Code3, RouterBench,
  LLMRouterBench, and similar benchmarks are methodology, eval, or calibration
  evidence unless a route label is natural and reviewable.
- Redacted production review samples can become regression cases after AI
  review, human audit when needed, and schema/privacy validation.

Do not solve the data gap by bulk-translating English benchmark data and
presenting it as Chinese quality evidence. Do use English routing datasets and
methods to validate the scoring mechanism and baseline comparisons.

## Current State

Implemented:

- `intentmux` / `lite` / `deep` model semantics and LiteLLM sidecar entry;
- metadata-only route audit logs and optional local prompt review logs;
- health reports, route budgets, review-candidate selection;
- smoke evals and baseline comparison: `current-router`, `always-lite`,
  `always-deep`, `hard-rule-only`;
- tracked public example assets:
  `examples/route_bank.sample.yaml` and `examples/eval_bank.sample.yaml`;
- embedding decisions expose route-bank match provenance through
  `match_source`, `match_index`, and `match_text_sha256`;
- route-bank embedding vectors persist in the runtime cache and invalidate on
  route-bank or embedding-model changes;
- Aurelio route kernel as the default through `ROUTER_ROUTE_KERNEL=aurelio`;
  default mode is `HybridRouter + HybridLocalIndex`, with `basic` retained as
  fallback/debug baseline;
- quality report generation from eval JSON and route summaries.
- generic AI review packet generation and AI review summary validation;
- daily health quality artifacts under `<log-dir>/quality/<day>/`: route
  summary JSON, eval baselines, quality report, review candidates, and AI
  review packet paths.
- route/eval/calibration asset generation from public sources, with generated
  semantic-set outputs kept as local or runtime artifacts by default.

Not closed:

- accepted findings are not routinely imported into redacted regression cases;
- threshold and margin changes still require repeated representative evidence
  before production policy changes;
- full-history logs still include legacy `fast` / `strong`, so current policy
  analysis must prefer current-day or post-migration logs.

## Active Work Order

Do these in order. Do not start a new architecture direction while the default
router is in log-driven maintenance.

1. Keep this control surface, evidence status, log-driven loop, and plan
   registry consistent.
2. Keep Aurelio as the default mature routing dependency and keep `basic` as a
   fallback/debug baseline.
3. Use mature public data and generated calibration assets for evidence; do not
   promote private logs or AI-invented examples into the main public eval.
4. Add a learning import gate for accepted redacted cases when log review shows
   a repeated need.
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
- Dataset-pipeline v2 execution baseline:
  `docs/router_data_pipeline_research.md`
