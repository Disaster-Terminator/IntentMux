# Router Quality Research

This note records the product direction for improving IntentMux routing quality
without turning it into a large router platform.

## Position

IntentMux remains a lightweight LiteLLM sidecar with a two-tier product model:

- `fast`: low-risk requests routed to the economical model group.
- `strong`: coding, debugging, agent, security, incident, and high-risk requests routed to the stronger model group.

The runtime should stay small: OpenAI-compatible proxying, route selection,
structured audit logs, and validation gates. Training routers, hosting vector
databases, or replacing LiteLLM are out of scope.

## Mature Patterns To Borrow

Semantic Router uses explicit `Route` objects with example utterances, encoders,
indexes, confidence scores, and thresholds. Its core workflow is still the right
shape for IntentMux: define routes, encode route examples, compare incoming
queries by similarity, and only route when confidence is high enough.

RouteLLM and RoRF are useful mainly as product constraints, not as runtime
dependencies. They reinforce a strong/weak model-pair framing, threshold
calibration, cost-quality tradeoff measurement, and evaluation before rollout.
Their trained routers and preference pipelines are heavier than IntentMux should
adopt.

LLMRouterBench is a warning against overbuilding. It reports that many router
methods perform similarly under unified evaluation and that careful model
selection and simple baselines remain hard to beat. For IntentMux, that means
route quality should improve through sourced evaluation data and calibration
first, not through a new classifier.

## Corpus Policy

IntentMux must not self-generate semantic routing corpora. Route-bank candidates
come from:

- mature public datasets declared in `config/route_sources.yaml`;
- redacted production review samples imported with
  `scripts/import_review_samples.py`;
- hand-written minimal seed examples in `config/routes.yaml` and example runtime
  homes.

Generated route banks must retain source names. Source manifests must include
homepages and license URLs where available. Runtime code must not depend on
Hugging Face or dataset tooling; dataset ingestion remains an offline asset build
step.

## Current Source Set

`config/route_sources.yaml` currently declares:

- MASSIVE zh-CN / zh-TW general assistant utterances for `fast`.
- SWE-bench issue statements for `strong`.
- MBPP code-generation prompts for `strong`.
- HumanEval prompts for `strong`.

These sources are chosen because they map naturally to the product's two tiers:
general assistant traffic should usually stay cheap, while code generation and
real issue resolution should be strong by default unless later evaluation proves
otherwise.

## Next Quality Loop

1. Build or refresh route banks from declared mature sources only.
2. Merge redacted production review samples into eval cases.
3. Run route evals before changing production config.
4. Compare route distribution and error budgets against the previous production
   health report.
5. Promote the new route bank only through the production rollout gate.

The goal is to reduce excessive `low_confidence` routing with sourced examples,
while preserving conservative fallback to `fast` when IntentMux cannot make a
defensible decision.

