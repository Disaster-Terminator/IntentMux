# Route Naming Migration Plan

## Decision

IntentMux keeps two separate naming layers:

- LiteLLM sidecar entry: `semantic-router`.
- Direct IntentMux gateway entry: `auto`.
- Product route ids and explicit entries: `lite` and `deep`.

`fast` and `strong` were internal historical names, not external product
contracts. This migration removes them from current configs, samples, and primary
tests instead of preserving them as a user-facing compatibility surface.

`smart-router` remains reserved for LiteLLM's native router and must not be used
for IntentMux.

## Scope

1. Migrate repository defaults, runtime templates, route banks, eval samples, and
   tests from `fast`/`strong` to `lite`/`deep`.
2. Keep the local LiteLLM sidecar model entry named `semantic-router`.
3. Keep direct gateway behavior for `model=auto|lite|deep`.
4. Add `ruff` to the development dependency group and run it in validation.
5. Sync `/path/to/intentmux-runtime/config/routes.yaml`.
6. Rebuild only the `intentmux` service and run production smoke checks.

## Non-goals

- Do not rename the LiteLLM `semantic-router` entry to `auto`.
- Do not touch LiteLLM's native `smart-router`.
- Do not rewrite old route logs.
- Do not redesign the routing algorithm.

## Validation

- `uv run --frozen python -m ruff check .`
- `uv run --frozen python -m pytest -q`
- `uv run --frozen python scripts/verify_route_contract.py`
- `uv run --frozen python scripts/eval_routes.py --mock-embeddings`
- Rebuild `intentmux` only.
- Verify `/ready`, direct decision smoke, and strict LiteLLM-entry E2E with
  `model=semantic-router`.
