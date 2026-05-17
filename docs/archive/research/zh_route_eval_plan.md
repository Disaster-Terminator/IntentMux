# Chinese Route Eval Plan Status

This document is retained as historical context. It is not the active execution
plan.

The current control surface is:

```text
docs/PROJECT_CONTROL.md
```

## Current Decision

IntentMux still needs Chinese-first routing evidence, but the project should not
build a large Chinese route-label dataset as the next step.

Use mature public data only when it naturally maps to the product's two tiers:

- general Chinese assistant utterances can become `lite` route-bank examples;
- coding, debugging, incident, security, or high-risk examples can become
  `deep` route-bank examples when source and license boundaries are clear;
- benchmarks without a natural route label are methodology references or
  local-only evidence, not automatic `lite` / `deep` truth.

The active path is the learnable quality loop:

```text
runtime logs
  -> deterministic candidate selection
  -> AI review packet
  -> human audit only for escalations and policy changes
  -> redacted regression cases or route-bank assets
  -> baseline comparison and quality report
```

## Historical Notes

Older plans used `fast` / `strong` names and assumed a Chinese eval bank could
be built directly from public benchmarks. That direction is superseded. Current
product names are `lite` / `deep`, and benchmark categories must not be treated
as route labels unless the mapping is natural and reviewable.
