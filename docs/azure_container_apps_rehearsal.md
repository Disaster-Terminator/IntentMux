# Azure Container Apps Rehearsal

This is a staging rehearsal for IntentMux only. Do not point production clients
at the hosted endpoint until the rollout gate in `docs/cloud_hosting.md` passes.

## Cost Guardrails

- Azure for Students credit is infrastructure-only for this rehearsal. Do not
  run model or embedding inference workloads on Azure under this budget.
- DigitalOcean credit is reserved for model calls and is not part of the
  IntentMux infrastructure rehearsal.
- Use Azure Container Apps consumption with `--min-replicas 0` and
  `--max-replicas 1`.
- Create the environment with `--logs-destination none` for rehearsal. Default
  Log Analytics workspaces can add cost.
- Prefer an ephemeral ACR Basic registry only for image transfer. Delete the
  rehearsal resource group after the run if it is not needed.
- Do not create Azure Files, Storage Accounts, VNETs, private endpoints, or
  always-on replicas in the first rehearsal.
- Set a budget alert on the subscription before leaving resources running.

Current rehearsal budget alert:

```text
resource group: intentmux-rg-staging
action group: intentmux-budget-action-group
receiver: ops@example.com
budget: intentmux-monthly-budget
amount: USD 20 monthly
thresholds: 50%, 80%, 100%
period: 2026-05-01T00:00:00Z to 2027-06-01T00:00:00Z
```

Azure CLI accepts the budget time period reliably with ISO timestamps:

```bash
az monitor action-group create \
  --resource-group intentmux-rg-staging \
  --name intentmux-budget-action-group \
  --short-name imuxbudg \
  --action email budget-email ops@example.com

az consumption budget create-with-rg \
  --resource-group intentmux-rg-staging \
  --budget-name intentmux-monthly-budget \
  --amount 20 \
  --category Cost \
  --time-grain Monthly \
  --time-period '{"startDate":"2026-05-01T00:00:00Z","endDate":"2027-06-01T00:00:00Z"}'
```

## Local Runtime Bundle

Build a cloud-safe runtime under the ignored `.intentmux-cloud/runtime` path:

```bash
uv run python scripts/build_cloud_runtime.py \
  --source-runtime /path/to/intentmux-runtime \
  --output-runtime .intentmux-cloud/runtime \
  --litellm-base-url https://configured-by-env.invalid \
  --embedding-url https://configured-by-env.invalid/v1/embeddings \
  --force
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
  -e ROUTER_EMBEDDING_URL=https://embedding.example.invalid/v1/embeddings \
  intentmux-azure-rehearsal:local
```

Expected local probe:

- `GET /health` returns `200` without auth.
- `GET /ready` returns `401` without auth.
- `GET /ready` with bearer auth returns `503` until real LiteLLM and embedding
  endpoints are configured.

## Azure Staging Shape

Recommended first rehearsal values:

```text
resource group: intentmux-rg-staging
location: eastus
container app env: intentmux-env-staging
container app: intentmux-staging
registry: intentmuxacr<shortsuffix>
cpu/memory: 0.25 CPU / 0.5Gi
replicas: min 0 / max 1
ingress: external, target port 4001
logs: none
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
ROUTER_LITELLM_BASE_URL=<hosted LiteLLM URL>
ROUTER_LITELLM_API_KEY=secretref:litellm-api-key
ROUTER_EMBEDDING_URL=<hosted or private tunnel embedding URL>
ROUTER_EMBEDDING_MODEL=<embedding model name>
```

Keep LiteLLM, embedding, databases, and monitoring out of this repository's
deployment scripts. This runbook only proves the IntentMux container surface.

## Azure Rehearsal Commands

Use one isolated resource group so all rehearsal costs can be removed at once:

```bash
az group create \
  --name intentmux-rg-staging \
  --location eastus \
  --tags project=intentmux env=rehearsal cost_guard=delete_when_done
```

Create a Basic ACR for image transfer:

```bash
az acr create \
  --name intentmuxacr0000 \
  --resource-group intentmux-rg-staging \
  --location eastus \
  --sku Basic \
  --admin-enabled false \
  --tags project=intentmux env=rehearsal cost_guard=delete_when_done
```

Create the Container Apps environment without Log Analytics:

```bash
az containerapp env create \
  --name intentmux-env-staging \
  --resource-group intentmux-rg-staging \
  --location eastus \
  --logs-destination none \
  --enable-workload-profiles false \
  --tags project=intentmux env=rehearsal cost_guard=delete_when_done
```

Push the locally tested image:

```bash
az acr login --name intentmuxacr0000 --expose-token --query accessToken -o tsv \
  | docker login intentmuxacr0000.azurecr.io \
      --username 00000000-0000-0000-0000-000000000000 \
      --password-stdin

docker tag intentmux-azure-rehearsal:local \
  intentmuxacr0000.azurecr.io/intentmux:rehearsal-<git-sha>
docker push intentmuxacr0000.azurecr.io/intentmux:rehearsal-<git-sha>
```

Create the staging app with scale-to-zero and a system-assigned identity for
ACR pull:

```bash
az containerapp create \
  --name intentmux-staging \
  --resource-group intentmux-rg-staging \
  --environment intentmux-env-staging \
  --image intentmuxacr0000.azurecr.io/intentmux:rehearsal-<git-sha> \
  --target-port 4001 \
  --ingress external \
  --transport http \
  --min-replicas 0 \
  --max-replicas 1 \
  --cpu 0.25 \
  --memory 0.5Gi \
  --system-assigned \
  --registry-server intentmuxacr0000.azurecr.io \
  --registry-identity system \
  --secrets intentmux-inbound-api-key="$INTENTMUX_REHEARSAL_KEY" \
  --env-vars \
    INTENTMUX_HOME=/data \
    ROUTER_CONFIG=/data/config/routes.yaml \
    ROUTER_CLOUD_MODE=true \
    ROUTER_REQUIRE_ROUTE_BANK=true \
    ROUTER_PROMPT_LOG_MODE=off \
    ROUTER_AUDIT_LOG_ENABLED=true \
    ROUTER_INBOUND_API_KEY=secretref:intentmux-inbound-api-key \
    ROUTER_LITELLM_BASE_URL=https://litellm.example.invalid \
    ROUTER_EMBEDDING_URL=https://embedding.example.invalid/v1/embeddings \
    ROUTER_EMBEDDING_MODEL=text-embedding-jina-embeddings-v5-text-small-retrieval@q8_0 \
  --tags project=intentmux env=rehearsal cost_guard=delete_when_done
```

## Hosted Probe

Some local proxy setups can stall on ACA ingress. If regular `curl` times out
after a successful `HTTP 200 Connection established`, retry with
`--noproxy '*'`.

```bash
FQDN=intentmux-staging.example.azurecontainerapps.io

curl --noproxy '*' -i "https://$FQDN/health"
curl --noproxy '*' -i "https://$FQDN/ready"
curl --noproxy '*' -i -H "Authorization: Bearer $INTENTMUX_REHEARSAL_KEY" \
  "https://$FQDN/ready"
curl --noproxy '*' -i "https://$FQDN/v1/models"
curl --noproxy '*' -i -H "Authorization: Bearer $INTENTMUX_REHEARSAL_KEY" \
  "https://$FQDN/v1/models"
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
az group delete --name intentmux-rg-staging
```
