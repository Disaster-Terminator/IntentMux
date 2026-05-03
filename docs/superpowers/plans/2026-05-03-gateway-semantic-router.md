# Gateway Semantic Router Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and verify a lightweight Chinese OpenAI-compatible sidecar that rewrites `model=smart-router` to local LiteLLM route groups.

**Architecture:** FastAPI receives chat completions, `Router` decides whether and how to rewrite the model, and `LiteLLMProxy` forwards to the existing LiteLLM gateway. Route utterances and thresholds live in YAML so tuning does not require code changes.

**Tech Stack:** Python 3.11+, uv, FastAPI, httpx, numpy, PyYAML, pytest.

---

### Task 1: Core Routing

**Files:**
- Create: `router/config.py`
- Create: `router/embedding.py`
- Create: `router/routing.py`
- Create: `config/routes.yaml`
- Test: `tests/test_routing.py`

- [ ] Write failing tests for pass-through, hard rules, embedding decisions, and fallback.
- [ ] Run `uv run pytest tests/test_routing.py -q` and verify failures come from missing implementation.
- [ ] Implement config loading, embedding client protocol, and routing decisions.
- [ ] Run `uv run pytest tests/test_routing.py -q` and verify the tests pass.

### Task 2: OpenAI-Compatible HTTP Sidecar

**Files:**
- Create: `router/proxy.py`
- Create: `router/app.py`
- Create: `router/__init__.py`
- Test: `tests/test_app.py`

- [ ] Write failing tests for `/health`, non-`smart-router` pass-through, and `smart-router` rewrite.
- [ ] Run `uv run pytest tests/test_app.py -q` and verify failures come from missing HTTP implementation.
- [ ] Implement FastAPI routes and LiteLLM forwarding.
- [ ] Run `uv run pytest tests/test_app.py -q` and verify the tests pass.

### Task 3: Eval and Operations

**Files:**
- Create: `config/eval_cases.yaml`
- Create: `scripts/eval_routes.py`
- Modify: `README.md`

- [ ] Write eval cases for Chinese cheap/pro/probe routing.
- [ ] Add a script that loads cases and exits non-zero on mismatches.
- [ ] Document local run commands and environment variables.
- [ ] Run `uv run pytest -q` and `uv run python scripts/eval_routes.py --mock-embeddings`.

### Task 4: Live Verification and GitHub Private Repo

**Files:**
- Modify: `README.md`

- [ ] Start the sidecar on `127.0.0.1:4001`.
- [ ] Verify `/health`.
- [ ] Send a real `model=smart-router` Chinese coding request through the sidecar to LiteLLM and confirm the sidecar rewrites to `pro-router` in logs.
- [ ] Commit the repository.
- [ ] Create private GitHub repo `Disaster-Terminator/gateway-semantic-router`.
- [ ] Push `main`.

