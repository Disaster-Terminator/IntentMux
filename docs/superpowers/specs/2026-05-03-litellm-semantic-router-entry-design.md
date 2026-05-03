# LiteLLM Semantic Router Entry Design

## Goal

Expose `gateway-semantic-router` through the existing LiteLLM `:4000` entrypoint
with minimal upstream change. Upstream clients keep their LiteLLM base URL and
API key, and opt in by using `model=semantic-router`.

## Confirmed Constraints

- LiteLLM supports OpenAI-compatible upstreams through `model_list` entries that
  map a client-facing `model_name` to `litellm_params.model: openai/<name>` and
  `api_base: <endpoint>/v1`.
- The current LiteLLM config already uses `general_settings.master_key:
  os.environ/LITELLM_MASTER_KEY`.
- The production LiteLLM config must not be changed during the internal spike.
- LiteLLM's native router remains responsible for provider-level order,
  fallback, cooldown, retry, and provider selection.
- `gateway-semantic-router` is responsible only for semantic task routing from
  `semantic-router` to `cheap-router`, `pro-router`, or `free-probe-router`.

## Recommended Production Shape

```text
client/framework
  -> LiteLLM:4000
       model=semantic-router
  -> gateway-semantic-router sidecar
       route_model=semantic-router
       target=cheap-router/pro-router/free-probe-router
  -> LiteLLM:4000
       provider/order/fallback/cooldown
  -> provider
```

This keeps existing upstream base URLs stable:

```text
base_url: http://127.0.0.1:4000
model: semantic-router
```

LiteLLM's existing `smart-router` should remain the native complexity router.
The semantic sidecar should not reuse `smart-router` as its public entry name
because that makes the same model name mean different things depending on
whether the request entered through `:4000` or `:4001`.

## Spike Configuration

The internal spike uses two temporary configs and does not modify
`/path/to/gateway/litellm/config.yaml`.

- `spikes/semantic-router-litellm/sidecar-routes.yaml`
  - Sets `route_model: semantic-router`.
  - Routes back to production LiteLLM at `http://litellm:4000`.
- `spikes/semantic-router-litellm/litellm-proxy-config.yaml`
  - Exposes only one model: `semantic-router`.
  - Maps it to `openai/semantic-router`.
  - Uses `api_base: http://gateway-semantic-router-spike:4011/v1`.

The temporary topology is:

```text
test client
  -> litellm-semantic-router-spike:4010
       model=semantic-router
  -> gateway-semantic-router-spike:4011
       target=pro-router for hard_rule:线上
  -> production litellm:4000
       model=pro-router
```

## Verified Evidence

Non-streaming request through the temporary LiteLLM entry:

```text
POST http://litellm-semantic-router-spike:4010/v1/chat/completions
model=semantic-router
status 200
json_model semantic-router
```

Streaming request through the temporary LiteLLM entry:

```text
POST http://litellm-semantic-router-spike:4010/v1/chat/completions
model=semantic-router
stream=true
status 200
chunks 2
starts_with_data True
```

Sidecar route evidence:

```json
{"event":"route_complete","source_model":"semantic-router","target_model":"pro-router","reason":"hard_rule:线上","stream":false,"upstream_status":200}
{"event":"route_complete","source_model":"semantic-router","target_model":"pro-router","reason":"hard_rule:线上","stream":true,"upstream_status":200}
```

## Compatibility Finding

The first proxy-level spike failed even though the sidecar returned HTTP 200.
Root cause was duplicate `Server` response headers: the sidecar copied upstream
LiteLLM's `server` header while Uvicorn also generated its own. LiteLLM proxy's
async OpenAI-compatible path uses an aiohttp transport that rejects duplicate
`Server` headers.

The fix is to drop `server` and `date` in `router.proxy.response_headers()`.
This is covered by `tests/test_proxy.py`.

## Risk Assessment

- **Recursive routing:** The sidecar must rewrite `semantic-router` only to
  `cheap-router`, `pro-router`, or `free-probe-router`. It must never forward
  `semantic-router` back to LiteLLM.
- **Authentication:** The spike uses `LITELLM_MASTER_KEY` to prove the chain.
  Production should prefer an internal LiteLLM virtual key limited to the three
  target model groups.
- **Observability:** LiteLLM does not preserve the sidecar's route headers in
  the outer `:4000` response. Route decisions must be read from sidecar
  structured logs, or a later observability enhancement must explicitly publish
  route metadata elsewhere.
- **Correlation:** In production E2E, LiteLLM's model-entry path did not forward
  client-supplied `x-request-id`, `metadata.semantic_router_request_id`, or
  `user` to the sidecar. Current E2E therefore verifies route logs by recent
  route shape. Exact cross-layer correlation remains a follow-up item for a
  LiteLLM callback, OTEL integration, or front-door reverse proxy.
- **Endpoint coverage:** The current sidecar supports `/v1/chat/completions`
  with non-stream and SSE stream. LiteLLM remains the public entry for model
  listing, UI, auth, budgets, and other proxy endpoints. `/v1/responses` is not
  covered by this spike.
- **Latency:** The entry adds one local HTTP hop and one embedding call for
  non-hard-rule semantic routing. Hard rules avoid embedding latency.

## Production Acceptance Criteria

Before adding `semantic-router` to production LiteLLM config:

1. Production sidecar config uses `route_model: semantic-router`.
2. LiteLLM adds a single `model_name: semantic-router` entry pointing to the
   sidecar `/v1` base URL.
3. Existing `smart-router`, `cheap-router`, `pro-router`, and
   `free-probe-router` entries remain intact.
4. Non-streaming `model=semantic-router` through LiteLLM `:4000` returns HTTP
   200.
5. Streaming `model=semantic-router` through LiteLLM `:4000` returns HTTP 200
   and emits SSE `data:` chunks.
6. Sidecar logs show `source_model=semantic-router`,
   `target_model=pro-router` for a hard-rule prompt, and `upstream_status=200`.
7. A low-risk prompt routes to `cheap-router`.
8. A free-probe prompt routes to `free-probe-router`.
9. No prompt text or Authorization token appears in sidecar logs.
10. Rollback is documented as removing the `semantic-router` model entry or
    changing clients back to their previous model.

## Internal Spike Commands

Start temporary sidecar:

```bash
docker run -d --rm \
  --name gateway-semantic-router-spike \
  --network litellm_default \
  --network-alias gateway-semantic-router-spike \
  -v /path/to/gateway/gateway-semantic-router/spikes/semantic-router-litellm/sidecar-routes.yaml:/app/config/routes.yaml:ro \
  --add-host host.docker.internal:host-gateway \
  -e ROUTER_HOST=0.0.0.0 \
  -e ROUTER_PORT=4011 \
  -e ROUTER_LITELLM_BASE_URL=http://litellm:4000 \
  -e ROUTER_EMBEDDING_URL=http://host.docker.internal:1234/v1/embeddings \
  litellm-gateway-semantic-router:latest
```

Start temporary LiteLLM proxy:

```bash
docker run -d --rm \
  --name litellm-semantic-router-spike \
  --network litellm_default \
  -p 4010:4010 \
  --env-file /path/to/gateway/litellm/.env \
  -v /path/to/gateway/gateway-semantic-router/spikes/semantic-router-litellm/litellm-proxy-config.yaml:/app/config.yaml:ro \
  docker.litellm.ai/berriai/litellm:v1.83.14-stable \
  --config /app/config.yaml \
  --port 4010
```

Stop temporary containers:

```bash
docker stop litellm-semantic-router-spike gateway-semantic-router-spike
```
