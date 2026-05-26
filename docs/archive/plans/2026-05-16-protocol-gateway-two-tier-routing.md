# Protocol Gateway And Two-Tier Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make IntentMux a protocol-trustworthy OpenAI-compatible gateway while preserving the current LiteLLM sidecar as a backward-compatible deployment mode and converging on the lightweight two-tier `lite` / `deep` routing model.

**Architecture:** Treat IntentMux as a gateway product with a sidecar-compatible deployment mode. The gateway layer owns OpenAI-compatible endpoints, request ids, streaming pass-through, error classes, and privacy-safe logs. The routing layer owns `auto` / `lite` / `deep` entry semantics, explicit overrides, agent signals, hard rules, embedding fallback, and route-bank evaluation. The existing LiteLLM sidecar path shares the same routing policy, audit log, readiness, and route bank.

**Tech Stack:** FastAPI, httpx, pytest, uv, Docker Compose, existing `router.app`, `router.routing`, `router.proxy`, and `router.observability` modules.

---

## Background

The product direction should borrow two mature patterns without copying either wholesale:

- Crush and OpenCode use explicit large/small model roles. They clarify product semantics: main work goes to a stronger model, lightweight support work can use a cheaper model.
- RouteLLM and semantic-router perform request-level routing. RouteLLM frames the decision as strong-vs-weak thresholding; semantic-router frames it as route utterances, embeddings, confidence thresholds, and eval-driven calibration.

IntentMux should keep a small runtime. It should not become a provider marketplace, model pool manager, admin console, or training router. LiteLLM remains the recommended upstream provider/model-group/fallback/auth/budget layer. IntentMux owns a low-intrusion OpenAI-compatible model entry that can decide between product-level `lite` and `deep` routes.

## Product Shape

IntentMux is a lightweight local AI gateway with LiteLLM sidecar compatibility.

- In gateway mode, clients call IntentMux directly as an OpenAI-compatible `base_url` and request `model=auto`, `model=lite`, or `model=deep`.
- In sidecar mode, existing LiteLLM deployments keep the current topology. Clients can continue entering through LiteLLM and route via the legacy `semantic-router` model entry.
- Both modes use the same routing core: explicit route overrides, agent structure signals, hard-rule escalation, semantic route-bank scoring, audit logging, readiness checks, and health reports.
- Gateway mode is a product superset of sidecar mode. It must not break the existing sidecar contract or force current users to change deployment topology.
- IntentMux does not own provider routing, provider fallback, provider credentials, virtual keys, budgets, or model pools. Those remain upstream concerns, with LiteLLM as the default recommended upstream.

The product sentence should become:

```text
IntentMux is a lightweight local AI gateway that routes OpenAI-compatible requests between lite and deep model tiers with auditable decisions, while preserving LiteLLM sidecar compatibility.
```

Chinese product sentence:

```text
IntentMux 是一个轻量本地 AI 网关，把 OpenAI 兼容请求按复杂度路由到 lite / deep 两档模型，并保留 LiteLLM sidecar 兼容部署。
```

## Compatibility Modes

### Gateway Mode

Gateway mode is the new public product shape.

```text
client -> IntentMux base_url -> route_id(lite/deep) -> upstream OpenAI-compatible model
```

Default upstream remains LiteLLM, but the contract is OpenAI-compatible upstream rather than LiteLLM-only.

### LiteLLM Sidecar Mode

Sidecar mode is the existing production-compatible deployment shape.

```text
client -> LiteLLM model entry -> IntentMux sidecar -> route_id -> LiteLLM target model group
```

This mode stays supported for current local production. The current `semantic-router` entry and `fast` / `strong` route ids must have regression coverage before canonical `auto` / `lite` / `deep` migration changes land.

### Shared Core

Both modes share:

- routing policy and route-bank assets;
- structured route audit logs;
- prompt review logs when explicitly enabled for local review;
- readiness and health checks;
- preflight and LiteLLM-entry E2E checks;
- route quality reports and daily health outputs.

They differ only in entry topology and model-name compatibility.

## Confirmed Product Boundaries

- Public entry model names:
  - `auto`: preferred new generic entry model.
  - `semantic-router`: backward-compatible legacy entry model.
  - `lite`: explicit lightweight/low-cost tier override.
  - `deep`: explicit deep-reasoning/high-capability tier override.
- Public model listing:
  - `/v1/models` should return only canonical entries: `auto`, `lite`, and `deep`.
  - `semantic-router` remains accepted as a backward-compatible alias but should be documented as legacy rather than advertised as the preferred public entry.
- Internal route ids:
  - Only `lite` and `deep` are first-class product route ids for now.
  - Deployment target model names remain configuration values, not product route ids.
  - Examples may use placeholder targets such as `local-lite-model` and `local-deep-model`; production deployments map these to their own LiteLLM model groups or other OpenAI-compatible upstream model names.
- Routing behavior:
  - `auto` and `semantic-router` run normal routing.
  - `lite` and `deep` force explicit route ids when used as requested model names.
  - `metadata.route_id` remains the explicit override mechanism for clients that keep using `auto` / `semantic-router`.
- Gateway compatibility:
  - OpenAI-compatible request and stream pass-through must be reliable before route quality is claimed.
  - `/v1/models` should advertise the synthetic product entries and avoid leaking local LiteLLM group names unless explicitly configured later.
- Authentication and secret boundaries:
  - inbound IntentMux API keys, upstream LiteLLM/OpenAI-compatible API keys, and embedding API keys remain separate configuration values.
  - IntentMux must not rely on raw client `Authorization` pass-through for gateway mode.
- Failure strategy:
  - embedding degradation remains fail-open to the configured fallback route for routed chat requests;
  - LiteLLM or upstream transport/status failures fail closed with controlled, redacted gateway errors.
- Observability migration:
  - add stable `error_class` and `status` alongside existing `error_type` and `upstream_status`;
  - migrate scripts and reports later instead of breaking current local health checks in the same change.
- Request-id safety:
  - use a strict ASCII token policy for request ids;
  - reject whitespace, non-ASCII, malformed, and obvious secret-bearing values.

## Naming And Migration

The public two-tier names are `lite` and `deep`.

- `lite` means lightweight, lower-cost, lower-risk handling. It does not mean bad or unusable.
- `deep` means deeper reasoning, higher capability, and higher confidence for code, tools, long context, incidents, and security-sensitive work. It avoids the product baggage of `pro`, the model-size implication of `large`, and the negative opposite of `weak`.

Current repository and local runtime examples may still contain `fast` / `strong`.
Migration should be explicit:

- accept `fast` as a backward-compatible alias for `lite`;
- accept `strong` as a backward-compatible alias for `deep`;
- first freeze and test the legacy sidecar contract, then introduce canonical `lite` / `deep`;
- log canonical route ids as `lite` / `deep` after migration, while preserving enough legacy fields or aliases for existing health scripts during the transition;
- keep target model names deployment-specific and never infer product route ids from names such as `cheap`, `pro`, `free`, or provider-specific model groups.

`model=lite` and `model=deep` should be explicit override entries. When a caller chooses one of them, IntentMux should obey that route. Hard rules, agent signals, and semantic scoring apply to `auto` and legacy `semantic-router`, not to explicit `lite` / `deep` requests.

## File Structure

- `router/config.py`: add entry model aliases and validation for synthetic entry names.
- `router/routing.py`: resolve requested model names into `auto` routing or explicit route ids.
- `router/app.py`: add `/v1/models`, keep `/health`, `/ready`, `/v1/chat/completions`, and `/v1/semantic-router/decision` behavior stable.
- `router/proxy.py`: keep pass-through behavior; only change if request-id or error mapping requires it.
- `router/observability.py`: add stable `error_class` and `status` fields while preserving existing diagnostic fields.
- `tests/test_routing.py`: cover `auto`, legacy `semantic-router`, `lite`, `deep`, and metadata precedence.
- `tests/test_app.py`: cover `/v1/models`, chat pass-through, structured log schema, and privacy.
- `tests/test_proxy.py`: cover header forwarding and request-id safety if proxy-level behavior changes.
- `tests/test_protocol_gateway.py`: create if `tests/test_app.py` becomes too large; use a fake OpenAI-compatible HTTP upstream for realistic protocol tests.
- `docs/agent_framework_integration.md`: document `auto` / `lite` / `deep` usage for agent clients.
- `README.md` and `README.en.md`: document default model entry names and compatibility limits.

## Task 1: Confirm Entry Model Contract In Config And Routing

**Files:**
- Modify: `router/config.py`
- Modify: `router/routing.py`
- Test: `tests/test_routing.py`

- [ ] **Step 1: Write failing tests for model-name semantics**

Add tests showing that:

```python
@pytest.mark.asyncio
async def test_auto_entry_model_uses_normal_routing():
    route_settings = settings().model_copy(update={"route_model": "auto"}, deep=True)
    vectors = {
        "翻译成中文": [1.0, 0.0, 0.0],
        "总结这篇文章": [1.0, 0.0, 0.0],
        "分析这个线上 bug": [0.0, 1.0, 0.0],
        "代码审查": [0.0, 1.0, 0.0],
        "把这句话翻译成英文": [1.0, 0.0, 0.0],
    }
    router = Router(route_settings, FakeEmbeddingClient(vectors))

    decision = await router.decide(
        {"model": "auto", "messages": [{"role": "user", "content": "把这句话翻译成英文"}]}
    )

    assert decision.route_id == "lite"
    assert decision.target_model == "local-lite-model"
    assert decision.policy_id == "embedding"
```

```python
@pytest.mark.asyncio
async def test_lite_and_deep_model_names_are_explicit_route_overrides():
    router = Router(settings(), FakeEmbeddingClient({}, fail=True))

    lite_decision = await router.decide(
        {"model": "lite", "messages": [{"role": "user", "content": "密钥疑似泄漏"}]}
    )
    deep_decision = await router.decide(
        {"model": "deep", "messages": [{"role": "user", "content": "你好"}]}
    )

    assert lite_decision.route_id == "lite"
    assert lite_decision.target_model == "local-lite-model"
    assert lite_decision.policy_id == "explicit"
    assert deep_decision.route_id == "deep"
    assert deep_decision.target_model == "local-deep-model"
    assert deep_decision.policy_id == "explicit"
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
rtk uv run pytest tests/test_routing.py::test_auto_entry_model_uses_normal_routing tests/test_routing.py::test_lite_and_deep_model_names_are_explicit_route_overrides -q
```

Expected: tests fail because current routing only treats `settings.route_model` as the routed entry and passes through `lite` / `deep` as upstream models.

- [ ] **Step 3: Implement minimal route-entry resolution**

In `router/routing.py`, add a helper that classifies the requested model:

```python
def _requested_route_id(self, source_model: Any) -> str | None:
    if isinstance(source_model, str) and source_model in self.settings.routes:
        return source_model
    return None
```

Update `Router.decide()` so `lite` / `deep` are handled before pass-through:

```python
source_model = request_json.get("model")
requested_route_id = self._requested_route_id(source_model)
if requested_route_id is not None:
    return RoutingDecision(
        route_id=requested_route_id,
        target_model=self._target_model_for_route(requested_route_id),
        source_model=source_model,
        reason="explicit",
        policy_id="explicit",
        rewrite=True,
    )
if source_model != self.settings.route_model:
    return RoutingDecision(...)
```

If we decide to support both `auto` and `semantic-router` immediately, add a settings field such as `entry_model_aliases: list[str] = ["semantic-router"]` and treat `source_model in {route_model, *entry_model_aliases}` as auto-routed.

- [ ] **Step 4: Run focused routing tests**

Run:

```bash
rtk uv run pytest tests/test_routing.py -q
```

Expected: all routing tests pass.

- [ ] **Step 5: Commit**

```bash
rtk git add router/config.py router/routing.py tests/test_routing.py
rtk git commit -m "route: define auto lite deep entry semantics"
```

## Task 2: Add `/v1/models` Synthetic Model Listing

**Files:**
- Modify: `router/app.py`
- Test: `tests/test_app.py` or `tests/test_protocol_gateway.py`

- [ ] **Step 1: Write failing endpoint test**

Add a test that calls `/v1/models` and expects OpenAI-shaped model objects:

```python
def test_models_endpoint_lists_synthetic_product_models():
    app = create_app(settings(), FakeRouter(...), FakeProxy(...))
    client = TestClient(app)

    response = client.get("/v1/models")

    assert response.status_code == 200
    payload = response.json()
    assert payload["object"] == "list"
    ids = [item["id"] for item in payload["data"]]
    assert ids == ["auto", "lite", "deep"]
    assert "semantic-router" not in ids
    assert all(item["object"] == "model" for item in payload["data"])
```

- [ ] **Step 2: Run test and confirm failure**

Run:

```bash
rtk uv run pytest tests/test_app.py::test_models_endpoint_lists_synthetic_product_models -q
```

Expected: 404 until `/v1/models` exists.

- [ ] **Step 3: Implement endpoint**

In `create_app()`, add:

```python
@app.get("/v1/models")
async def list_models() -> dict[str, Any]:
    created = 0
    return {
        "object": "list",
        "data": [
            {"id": "auto", "object": "model", "created": created, "owned_by": "intentmux"},
            {"id": "lite", "object": "model", "created": created, "owned_by": "intentmux"},
            {"id": "deep", "object": "model", "created": created, "owned_by": "intentmux"},
        ],
    }
```

Do not include local target model group names by default.

- [ ] **Step 4: Run focused app tests**

Run:

```bash
rtk uv run pytest tests/test_app.py::test_models_endpoint_lists_synthetic_product_models -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add router/app.py tests/test_app.py
rtk git commit -m "api: list synthetic intentmux models"
```

## Task 3: Stabilize Route Error Schema

**Files:**
- Modify: `router/observability.py`
- Modify: `router/app.py`
- Test: `tests/test_app.py`
- Test: `tests/test_router_log_summary.py` if summary parsing needs updates

- [ ] **Step 1: Write failing log-schema tests**

Add tests that route errors include stable fields:

```python
def test_route_error_log_includes_stable_error_class_and_status(caplog):
    ...
    route_error = next(record for record in records if record["event"] == "route_error")
    assert route_error["status"] is None
    assert route_error["error_class"] == "upstream_network_error"
    assert "error_type" in route_error
```

Add a status error case:

```python
def test_upstream_5xx_route_error_status_is_present():
    ...
    assert route_error["status"] == 503
    assert route_error["error_class"] == "upstream_server_error"
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
rtk uv run pytest tests/test_app.py -k "error_class or route_error" -q
```

Expected: missing `error_class` and sometimes missing `status`.

- [ ] **Step 3: Implement error class mapping**

In `router/observability.py`, add:

```python
def error_class_for(error: BaseException, upstream_status: int | None) -> str:
    if upstream_status == 401:
        return "upstream_auth_error"
    if upstream_status == 429:
        return "upstream_rate_limited"
    if upstream_status is not None and upstream_status >= 500:
        return "upstream_server_error"
    if type(error).__name__ in {"TimeoutError", "ReadTimeout", "ConnectTimeout"}:
        return "upstream_timeout"
    if type(error).__name__ in {"RemoteProtocolError", "ConnectError", "NetworkError"}:
        return "upstream_network_error"
    if type(error).__name__ == "UpstreamStatusError":
        return "upstream_bad_response"
    return "gateway_internal_error"
```

Update `route_record()` to always include:

```python
"status": upstream_status,
```

Update `log_route_error()` to include:

```python
"error_class": error_class_for(error, upstream_status),
```

Keep `error_type` and `upstream_status` for backward-compatible diagnostics.

- [ ] **Step 4: Run focused tests**

Run:

```bash
rtk uv run pytest tests/test_app.py tests/test_router_log_summary.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add router/observability.py router/app.py tests/test_app.py tests/test_router_log_summary.py
rtk git commit -m "observability: add stable gateway error classes"
```

## Task 4: Add Realistic Fake OpenAI Upstream Protocol Tests

**Files:**
- Create: `tests/test_protocol_gateway.py`
- Possibly modify: `router/proxy.py`

- [ ] **Step 1: Add fake upstream fixtures**

Create a small ASGI fake upstream with endpoints:

```python
@fake.post("/v1/chat/completions")
async def fake_chat(request: Request):
    payload = await request.json()
    if payload["stream"] is True:
        return StreamingResponse(
            iter([b"data: {\"choices\":[{\"delta\":{\"content\":\"hi\"}}]}\n\n", b"data: [DONE]\n\n"]),
            media_type="text/event-stream",
        )
    return JSONResponse({"id": "chatcmpl-test", "object": "chat.completion", "model": payload["model"], "choices": []})
```

- [ ] **Step 2: Test non-stream pass-through**

Assert that `/v1/chat/completions` maps model names but preserves safe fields:

```python
def test_nonstream_completion_passes_through_common_fields(fake_upstream):
    response = client.post("/v1/chat/completions", json={
        "model": "lite",
        "messages": [{"role": "user", "content": "hello"}],
        "temperature": 0.2,
        "top_p": 0.9,
        "max_tokens": 8,
        "custom_field": "kept",
    })
    assert response.status_code == 200
```

- [ ] **Step 3: Test stream pass-through**

Assert streamed bytes contain upstream SSE chunks and `[DONE]` without buffering the full body.

- [ ] **Step 4: Run tests and confirm current behavior**

Run:

```bash
rtk uv run pytest tests/test_protocol_gateway.py -q
```

Expected: tests pass if proxy already preserves behavior; otherwise implement the smallest proxy fix.

- [ ] **Step 5: Commit**

```bash
rtk git add tests/test_protocol_gateway.py router/proxy.py
rtk git commit -m "test: cover openai-compatible gateway passthrough"
```

## Task 5: Harden Request ID Safety

**Files:**
- Modify: `router/observability.py`
- Modify: `router/proxy.py` if forwarding changes
- Test: `tests/test_app.py`
- Test: `tests/test_proxy.py`

- [ ] **Step 1: Write failing tests for unsafe ids**

Add tests for:

```python
def test_unsafe_request_id_header_is_not_used_or_forwarded(caplog):
    response = client.post(
        "/v1/chat/completions",
        headers={"x-request-id": "Bearer sk-secret-token"},
        json={"model": "auto", "messages": [{"role": "user", "content": "hello"}]},
    )
    route_log = ...
    assert route_log["request_id_source"] == "generated"
    assert "secret" not in json.dumps(route_log)
```

- [ ] **Step 2: Implement request id validation**

In `router/observability.py`, add:

```python
SAFE_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

def safe_request_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    if not SAFE_REQUEST_ID_RE.fullmatch(value):
        return None
    lowered = value.lower()
    if "bearer" in lowered or "sk-" in lowered or "api_key" in lowered:
        return None
    return value
```

Use it for `x-request-id`, `x-correlation-id`, trace-derived ids, and metadata request ids.

- [ ] **Step 3: Run tests**

Run:

```bash
rtk uv run pytest tests/test_app.py tests/test_proxy.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
rtk git add router/observability.py router/proxy.py tests/test_app.py tests/test_proxy.py
rtk git commit -m "security: sanitize request ids"
```

## Task 6: Document The Contract

**Files:**
- Modify: `README.md`
- Modify: `README.en.md`
- Modify: `docs/agent_framework_integration.md`
- Modify: `docs/roadmap.md`

- [ ] **Step 1: Document model entries**

Add a concise table:

| Requested model | Meaning | Behavior |
| --- | --- | --- |
| `auto` | Preferred routed entry | Runs IntentMux routing |
| `semantic-router` | Legacy routed entry | Same as `auto` |
| `lite` | Explicit low tier | Routes to configured `lite.target_model` |
| `deep` | Explicit high tier | Routes to configured `deep.target_model` |

- [ ] **Step 2: Document compatibility scope**

State:

- Supports `/health`, `/ready`, `/v1/models`, `/v1/chat/completions`, and `/v1/semantic-router/decision`.
- Supports stream and non-stream chat completion pass-through.
- Does not claim full OpenAI API compatibility.
- Does not implement `/v1/responses`.
- Does not manage provider pools; use LiteLLM or another OpenAI-compatible upstream for that.
- Keeps inbound IntentMux auth, upstream auth, and embedding auth as separate secrets.
- Treats embedding degradation as route fallback, while upstream failures return controlled redacted gateway errors.

- [ ] **Step 3: Document local vs tracked boundary**

State:

- Tracked examples use generic paths and generic model names.
- Local runtime logs, prompt review logs, generated route banks, and production compose overrides remain outside git.
- A local rollout may use an operator-specific Compose file, but the public deployment instructions must not hardcode that path.

- [ ] **Step 4: Run docs-adjacent checks**

Run:

```bash
rtk uv run python scripts/preflight.py
rtk uv run pytest tests/test_config.py tests/test_verify_route_contract.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add README.md README.en.md docs/agent_framework_integration.md docs/roadmap.md
rtk git commit -m "docs: define intentmux gateway contract"
```

## Task 7: Production Rollout And Log Verification

**Files:**
- No tracked file changes unless a generic script gap is found.

- [ ] **Step 1: Verify clean git state**

Run:

```bash
rtk git status --short
```

Expected: no output.

- [ ] **Step 2: Run full test and preflight**

Run:

```bash
rtk uv run pytest -q
rtk uv run python scripts/preflight.py
```

Expected: all tests pass and preflight reports health, ready, nonstream, and stream PASS.

- [ ] **Step 3: Roll out only IntentMux in local Compose**

Run local rollout from the repo root:

```bash
INTENTMUX_COMPOSE_FILE=/path/to/docker-compose.yml \
INTENTMUX_SERVICE=intentmux \
INTENTMUX_BASE_URL=http://127.0.0.1:4001 \
rtk bash scripts/rollout_compose_intentmux.sh --yes --ready-timeout 90
```

Expected: script reports clean worktree, test pass, image build, container healthy, preflight PASS, and agent-signal smoke PASS.

- [ ] **Step 4: Verify runtime logs**

Run:

```bash
rtk uv run python scripts/intentmux_daily_health.py --log-dir /path/to/intentmux-runtime/logs --timezone Asia/Shanghai --min-route-records 1
```

Expected:

- `ready_ok=true`
- tolerant budget passes
- new route logs contain `request_id`, `route_id`, `target_model`, `policy_id`, `reason`, `status`, and `error_class` on errors
- prompt text is absent from route audit logs

- [ ] **Step 5: Push**

```bash
rtk git push origin main
```

Expected: `main` pushed successfully.

## Non-Goals For This Plan

- No new UI.
- No provider marketplace.
- No direct model pool manager.
- No `/v1/responses`.
- No Kubernetes deployment.
- No new embedding model or training router.
- No generated semantic corpus.
- No release tag or version bump.

## Resolved Decisions Before Execution

1. `auto` becomes the preferred public entry immediately; `semantic-router` remains a backward-compatible legacy alias.
2. `/v1/models` returns only canonical entries: `auto`, `lite`, and `deep`.
3. `model=lite` and `model=deep` are explicit overrides. IntentMux obeys them even if hard rules would choose the other tier.
4. Stable `error_class` and `status` are added alongside existing `error_type` and `upstream_status`; scripts migrate later.
5. Request ids use a strict ASCII token policy and reject whitespace, non-ASCII, malformed, and obvious secret-bearing values.
