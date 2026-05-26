# Azure Container Apps Rehearsal

This is a generic staging rehearsal template for the IntentMux container. It
proves only the IntentMux cloud surface. Keep account-specific domains, resource
names, budget alerts, email addresses, and live verification notes in private
operations docs outside this repository.

## Cost Guardrails

- Use an isolated resource group so all rehearsal resources can be deleted
  together.
- Do not run model or embedding inference workloads on the infrastructure
  rehearsal budget unless that is an explicit deployment decision.
- Use Azure Container Apps consumption with `--min-replicas 0` and
  `--max-replicas 1` for a first rehearsal.
- Use `--logs-destination none` unless a reviewed hosted log sink is part of the
  rehearsal.
- Prefer an ephemeral ACR Basic registry only for image transfer.
- Set a budget alert in the subscription before leaving resources running.
- Delete the rehearsal resource group after the run if it is not needed.

Example variables:

```bash
export AZURE_RESOURCE_GROUP=intentmux-rg-staging
export AZURE_LOCATION=eastus
export AZURE_CONTAINERAPP_ENV=intentmux-env-staging
export AZURE_CONTAINERAPP_NAME=intentmux-staging
export AZURE_ACR_NAME=intentmuxacr$(date +%m%d%H%M)
export INTENTMUX_IMAGE_TAG=rehearsal-$(git rev-parse --short HEAD)
```

## Runtime Bundle

Build a cloud-safe runtime under the ignored `.intentmux-cloud/runtime` path:

```bash
uv run python scripts/build_cloud_runtime.py \
  --source-runtime /path/to/local-intentmux-runtime \
  --output-runtime .intentmux-cloud/runtime \
  --litellm-base-url https://litellm.internal.example \
  --embedding-url https://embedding.example.com/v1/embeddings \
  --include-route-cache \
  --force
```

Verify the bundled cache matches the hosted embedding model before building the
image:

```bash
uv run python scripts/check_cloud_runtime.py .intentmux-cloud/runtime \
  --require-route-cache \
  --expected-embedding-model "$ROUTER_EMBEDDING_MODEL" \
  --expected-embedding-input-max-chars "$ROUTER_EMBEDDING_INPUT_MAX_CHARS"
```

The Azure Dockerfile embeds only this checked runtime into `/data`. Hosted
upstream URLs and keys are still provided by Container Apps environment
variables or secrets, so endpoint rotation does not require editing
`routes.yaml`.

## Local Image Probe

```bash
docker build \
  -f deploy/azure/Dockerfile \
  -t intentmux-azure-rehearsal:local \
  .

docker run --rm -p 4001:4001 \
  -e ROUTER_INBOUND_API_KEY=dev-intentmux-key \
  -e ROUTER_LITELLM_BASE_URL=https://litellm.example.invalid \
  -e ROUTER_EXPOSE_TARGET_MODEL_HEADER=false \
  -e ROUTER_EMBEDDING_URL=https://embedding.example.invalid/v1/embeddings \
  -e ROUTER_EMBEDDING_MODEL=example-embedding-model \
  intentmux-azure-rehearsal:local
```

Expected local probe:

- `GET /health` returns `200` without auth.
- `GET /ready` returns `401` without auth.
- `GET /ready` with bearer auth returns `503` until real LiteLLM and embedding
  endpoints are configured.

## Azure Staging Shape

Recommended first rehearsal shape:

```text
resource group: $AZURE_RESOURCE_GROUP
location: $AZURE_LOCATION
container app env: $AZURE_CONTAINERAPP_ENV
container app: $AZURE_CONTAINERAPP_NAME
registry: $AZURE_ACR_NAME
cpu/memory: 0.25 CPU / 0.5Gi
replicas: min 0 / max 1
ingress: external for isolated IntentMux rehearsal, internal behind LiteLLM for full gateway rehearsal
logs: none unless a reviewed log sink is configured
```

The container app should set:

```text
INTENTMUX_HOME=/data
ROUTER_CONFIG=/data/config/routes.yaml
ROUTER_CLOUD_MODE=true
ROUTER_REQUIRE_ROUTE_BANK=true
ROUTER_PROMPT_LOG_MODE=off
ROUTER_AUDIT_LOG_ENABLED=true
ROUTER_AUDIT_LOG_DIR=
ROUTER_INBOUND_API_KEY=secretref:intentmux-inbound-api-key
ROUTER_EXPOSE_TARGET_MODEL_HEADER=false
ROUTER_LITELLM_BASE_URL=<hosted LiteLLM URL>
ROUTER_LITELLM_API_KEY=secretref:litellm-api-key
ROUTER_EMBEDDING_URL=<OpenAI-compatible embedding URL>
ROUTER_EMBEDDING_MODEL=<embedding model>
ROUTER_EMBEDDING_API_KEY=secretref:embedding-api-key
ROUTER_EMBEDDING_TIMEOUT=60
ROUTER_EMBEDDING_INPUT_MAX_CHARS=8192
```

Keep LiteLLM, databases, and monitoring out of this repository's deployment
scripts. This runbook only proves the IntentMux container surface and hosted
embedding integration.

## Azure Rehearsal Commands

Create the resource group:

```bash
az group create \
  --name "$AZURE_RESOURCE_GROUP" \
  --location "$AZURE_LOCATION" \
  --tags project=intentmux env=staging cost_guard=delete_when_done
```

Create a Basic ACR for image transfer:

```bash
az acr create \
  --name "$AZURE_ACR_NAME" \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --location "$AZURE_LOCATION" \
  --sku Basic \
  --admin-enabled false \
  --tags project=intentmux env=staging cost_guard=delete_when_done
```

Create the Container Apps environment without Log Analytics:

```bash
az containerapp env create \
  --name "$AZURE_CONTAINERAPP_ENV" \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --location "$AZURE_LOCATION" \
  --logs-destination none \
  --enable-workload-profiles false \
  --tags project=intentmux env=staging cost_guard=delete_when_done
```

Push the locally tested image:

```bash
az acr login --name "$AZURE_ACR_NAME" --expose-token --query accessToken -o tsv \
  | docker login "$AZURE_ACR_NAME.azurecr.io" \
      --username 00000000-0000-0000-0000-000000000000 \
      --password-stdin

docker tag intentmux-azure-rehearsal:local \
  "$AZURE_ACR_NAME.azurecr.io/intentmux:$INTENTMUX_IMAGE_TAG"
docker push "$AZURE_ACR_NAME.azurecr.io/intentmux:$INTENTMUX_IMAGE_TAG"
```

Create the staging app with scale-to-zero and a system-assigned identity for
ACR pull:

```bash
az containerapp create \
  --name "$AZURE_CONTAINERAPP_NAME" \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --environment "$AZURE_CONTAINERAPP_ENV" \
  --image "$AZURE_ACR_NAME.azurecr.io/intentmux:$INTENTMUX_IMAGE_TAG" \
  --target-port 4001 \
  --ingress external \
  --transport http \
  --min-replicas 0 \
  --max-replicas 1 \
  --cpu 0.25 \
  --memory 0.5Gi \
  --system-assigned \
  --registry-server "$AZURE_ACR_NAME.azurecr.io" \
  --registry-identity system \
  --secrets \
    intentmux-inbound-api-key="$INTENTMUX_REHEARSAL_KEY" \
    litellm-api-key="$LITELLM_UPSTREAM_KEY" \
    embedding-api-key="$ROUTER_EMBEDDING_API_KEY" \
  --env-vars \
    INTENTMUX_HOME=/data \
    ROUTER_CONFIG=/data/config/routes.yaml \
    ROUTER_CLOUD_MODE=true \
    ROUTER_REQUIRE_ROUTE_BANK=true \
    ROUTER_PROMPT_LOG_MODE=off \
    ROUTER_AUDIT_LOG_ENABLED=true \
    ROUTER_AUDIT_LOG_DIR= \
    ROUTER_INBOUND_API_KEY=secretref:intentmux-inbound-api-key \
    ROUTER_EXPOSE_TARGET_MODEL_HEADER=false \
    ROUTER_LITELLM_BASE_URL="$ROUTER_LITELLM_BASE_URL" \
    ROUTER_LITELLM_API_KEY=secretref:litellm-api-key \
    ROUTER_EMBEDDING_URL="$ROUTER_EMBEDDING_URL" \
    ROUTER_EMBEDDING_MODEL="$ROUTER_EMBEDDING_MODEL" \
    ROUTER_EMBEDDING_API_KEY=secretref:embedding-api-key \
    ROUTER_EMBEDDING_TIMEOUT=60 \
    ROUTER_EMBEDDING_INPUT_MAX_CHARS=8192 \
  --tags project=intentmux env=staging cost_guard=delete_when_done
```

## Hosted Probe

Some local proxy setups can stall on ACA ingress. If regular `curl` times out
after a successful `HTTP 200 Connection established`, retry with
`--noproxy '*'`.

```bash
export INTENTMUX_FQDN=<container-app-fqdn>

curl --noproxy '*' -i "https://$INTENTMUX_FQDN/health"
curl --noproxy '*' -i "https://$INTENTMUX_FQDN/ready"
curl --noproxy '*' -i -H "Authorization: Bearer $INTENTMUX_REHEARSAL_KEY" \
  "https://$INTENTMUX_FQDN/ready"
curl --noproxy '*' -i "https://$INTENTMUX_FQDN/v1/models"
curl --noproxy '*' -i -H "Authorization: Bearer $INTENTMUX_REHEARSAL_KEY" \
  "https://$INTENTMUX_FQDN/v1/models"
```

Expected staging result before real upstreams are wired:

- `/health` returns `200`.
- unauthenticated `/ready` and `/v1/models` return `401`.
- authenticated `/v1/models` returns the canonical `intentmux`, `lite`, and
  `deep` model list.
- authenticated `/ready` returns `503` with `router.ok=true` and upstream
  LiteLLM/embedding failures.

## Cleanup

Delete the whole rehearsal resource group when the staging environment is no
longer needed:

```bash
az group delete --name "$AZURE_RESOURCE_GROUP"
```
