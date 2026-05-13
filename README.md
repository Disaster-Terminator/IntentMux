# IntentMux

> 轻量、可审计的 LiteLLM 意图分流 sidecar。<br>
> 按请求意图选择 `route_id`，再映射到你的本地 LiteLLM 模型组。

<p align="center">
  <img alt="runtime Python 3.11+" src="https://img.shields.io/badge/runtime-Python%203.11%2B-3776AB">
  <img alt="entry semantic-router" src="https://img.shields.io/badge/entry-semantic--router-0EA5E9">
  <img alt="gateway LiteLLM compatible" src="https://img.shields.io/badge/gateway-LiteLLM%20compatible-16A34A">
  <img alt="logs no prompt or token" src="https://img.shields.io/badge/logs-no%20prompt%20%7C%20token-7C3AED">
</p>
<p align="center">
  <img alt="built with FastAPI" src="https://img.shields.io/badge/built%20with-FastAPI-009688">
  <img alt="config YAML" src="https://img.shields.io/badge/config-YAML-CB171E">
  <img alt="tests pytest" src="https://img.shields.io/badge/tests-pytest-0A9EDC">
  <img alt="package uv" src="https://img.shields.io/badge/package-uv-DE5FE9">
  <img alt="license Apache-2.0" src="https://img.shields.io/badge/license-Apache--2.0-111827">
</p>

[English](README.en.md)

## 一句话

IntentMux 是一个本地优先的 OpenAI-compatible / LiteLLM-compatible 路由 sidecar：客户端仍然请求原来的 LiteLLM 入口，只把模型名切到 `semantic-router`，IntentMux 根据请求意图选择 `route_id`，再映射到实际部署中的 `target_model`。

<table>
  <tr>
    <td><strong>意图分流</strong><br>默认在 `fast` / `strong` 两档之间按意图和阈值分流。</td>
    <td><strong>低侵入接入</strong><br>保留 LiteLLM 作为 provider、fallback、限流和鉴权层。</td>
  </tr>
  <tr>
    <td><strong>可审计日志</strong><br>结构化记录 `route_complete` / `route_error`，不记录 prompt、token 或 bearer token。</td>
    <td><strong>生产前验证</strong><br>提供 preflight、LiteLLM-entry E2E、日志 summary 和 route-error budget gate。</td>
  </tr>
</table>

## 项目边界

IntentMux 不是模型提供商，也不是 LiteLLM 的替代品。它只处理进入 sidecar 的兼容入口模型：

```text
model=semantic-router -> route_id -> target_model -> LiteLLM model group
```

其他模型名默认透传给 LiteLLM。

默认示例配置使用 `fast`、`strong` 两个产品级 route id，并映射到 LiteLLM 模型组 `cheap-router`、`pro-router`。这些 `target_model` 是部署名，不是产品接口。代码仍支持用户自定义更多 route，但默认产品心智是高/低两档。

部署时建议把 IntentMux 作为 LiteLLM 旁路 sidecar 独立管理；不要把 LiteLLM 挂载目录、token、`.env` 或 provider 凭据加入本仓库。

## 适合什么场景

- 你已经有 LiteLLM / OpenAI-compatible gateway。
- 你想用很小的接入成本，把一部分请求按意图分到不同模型组。
- 你希望路由决策可回放、可审计、可用日志继续改进。
- 你不想引入一个大型调度平台，也不想让客户端大改端点。

IntentMux 的差异化不是“再造一个复杂 router”，而是轻量、本地、快速部署、日志可读。成熟的 provider 路由、fallback、限流和鉴权仍交给 LiteLLM。

默认路由方法借鉴 strong/weak 两档 LLM router 和 Semantic Router 的成熟做法：

```text
explicit override -> high-precision hard escalation -> semantic score + threshold -> fallback fast
```

`hard_rules` 只用于安全、密钥泄露、线上事故、数据损坏等高风险强制升级场景。
`PR`、`debug`、`部署`、`索引`、`异常`、`报错` 等容易被 agent 累积上下文污染的普通工程词，
默认交给语义样本、相似度分数和阈值判断，避免后续轻量请求长期粘在 `strong`。

## 快速运行

```bash
uv run python -m router.app
```

默认端点：

| 服务 | 地址 |
| --- | --- |
| IntentMux sidecar | `http://127.0.0.1:4001` |
| LiteLLM upstream | `http://127.0.0.1:4000` |
| Embedding upstream | `http://127.0.0.1:1234/v1/embeddings` |

常用环境变量：

- `ROUTER_CONFIG`
- `ROUTER_HOST`
- `ROUTER_PORT`
- `ROUTER_LITELLM_BASE_URL`
- `ROUTER_LITELLM_TIMEOUT`
- `ROUTER_EMBEDDING_URL`
- `ROUTER_EMBEDDING_MODEL`
- `ROUTER_ACCESS_LOG`
- `ROUTER_AUDIT_LOG_ENABLED`
- `ROUTER_AUDIT_LOG_DIR`
- `ROUTER_READINESS_TIMEOUT`

IntentMux 支持本地进程和容器两种运行方式。容器不是唯一部署形态；挂载目录也不是开发
必需项，而是生产持久化配置、语义资产和 audit JSONL 的推荐方式。

不挂载也可以启动容器：镜像默认读取内置的 `/app/config/routes.yaml`，适合快速试用。
但这时用户配置不在宿主机上，audit JSONL 若写入容器可写层，只能保证同一个容器重启后
仍在；删除容器、重建容器、升级镜像或被运行时清理后会丢失。Docker stdout/stderr 日志
由 Docker logging driver 管理，普通 `docker restart` 不会清空，但会受日志轮转、容器删除
和宿主机日志策略影响。

生产部署时推荐把 IntentMux 当成 LiteLLM 的并列 sidecar，并给它一个独立的运行时目录。下面是通用目录形态，不要求使用这些宿主机路径：

```text
litellm/
  docker-compose.yml
  config.yaml
  .env
  intentmux/
    config/routes.yaml
    semantic_sets/route_bank.yaml
    logs/routes/YYYY-MM-DD.jsonl
```

容器内约定：

```text
/app   # 镜像代码和内置样例
/data  # 用户挂载的 IntentMux home
```

compose 示例：

仓库提供通用 compose 示例：[examples/docker-compose.yml](examples/docker-compose.yml)。

```bash
mkdir -p .intentmux-home
cp -R examples/intentmux-home/. .intentmux-home/
docker compose -f examples/docker-compose.yml up -d --build
```

默认示例会把仓库根目录下的 `.intentmux-home/` 挂载到容器 `/data`，它已被 `.gitignore` 排除，适合本地试用。生产部署建议复制 [examples/intentmux-home](examples/intentmux-home) 到源码仓库外的持久化位置，再用 `INTENTMUX_HOME=/path/to/intentmux-home` 指向它。

可覆盖变量：

- `INTENTMUX_PORT`：宿主机暴露端口，默认 `4001`。
- `INTENTMUX_HOME`：宿主机上的 IntentMux home，默认 `../.intentmux-home`（相对 `examples/docker-compose.yml`）。
- `ROUTER_LITELLM_BASE_URL`：LiteLLM 上游地址，默认 `http://host.docker.internal:4000`。
- `ROUTER_EMBEDDING_URL`：embedding 上游地址，默认 `http://host.docker.internal:1234/v1/embeddings`。
- `ROUTER_EMBEDDING_MODEL`：embedding 模型名。

LiteLLM 入口模型示例见 [examples/litellm-model-entry.yaml](examples/litellm-model-entry.yaml)。如果 IntentMux 和 LiteLLM 在同一个 compose network 中，`api_base` 可以使用 `http://intentmux:4001/v1`；如果 LiteLLM 在宿主机或另一个网络里，请改成它能访问到的 IntentMux 地址。

更新同步规则：

- 只改 `/data/config/routes.yaml`、`/data/semantic_sets/route_bank.yaml` 或环境变量：重启 IntentMux sidecar，让启动时加载的配置和向量索引刷新。
- 改 Python 代码、`Dockerfile`、内置 `config/` 或 `examples/`：重新构建镜像，再重建 IntentMux sidecar。
- 只改 README、测试或离线脚本：不影响正在运行的容器，但仍应跑对应测试或校验脚本。

compose 部署的常用更新命令：

```bash
docker compose -f examples/docker-compose.yml build intentmux
docker compose -f examples/docker-compose.yml up -d intentmux
```

IntentMux 暂未实现热重载，生产变更按“配置重启、代码重建”的规则处理。

仓库里的 `examples/intentmux-home/` 是可复制的运行时目录模板。`/data` 不应放 LiteLLM 的 `.env`、provider token、数据库或原始 prompt。

运行时目录是用户部署资产，不是本仓库的源码内容。本仓库默认通过 `.gitignore` 排除
`*-runtime/` 和 `data/semantic_sets/*.yaml`，避免把用户语义资产、审计日志或生产配置误提交。
生产部署应把运行时目录单独备份和迁移。

其中 `config/routes.yaml` 定义产品级 `route_id` 到 LiteLLM `target_model` 的映射，
`semantic_sets/route_bank.yaml` 必须使用同一组 `route_id` 作为 key，例如
`fast`、`strong`，不能使用 `cheap-router`、`pro-router`
这类部署侧 target model 名称作为 key。

## LiteLLM 接入方式

低侵入接入方式是：客户端继续请求 LiteLLM `:4000`，只把模型名切到 `semantic-router`。

```text
client -> LiteLLM :4000, model=semantic-router
       -> IntentMux :4001
       -> route_id
       -> target_model
       -> LiteLLM model group
```

在 LiteLLM 中把 `semantic-router` 配置为指向 IntentMux sidecar 的模型入口后，客户端即可通过这个模型名触发意图分流。未命中该入口的模型名会保持透传。

## 配置模型

`config/routes.yaml` 的核心结构：

```yaml
route_model: semantic-router
fallback_route_id: fast

routes:
  fast:
    target_model: cheap-router
    description: 低风险、普通问答、解释、翻译、格式转换、轻量总结
    utterances:
      - 帮我解释一下这段概念

  strong:
    target_model: pro-router
    description: 代码、debug、架构、agent、多步推理、高风险判断
    utterances:
      - 这个线上 bug 为什么偶发
```

运行时校验会阻止递归配置：入口模型本身不能作为 route id 或 target model，`fallback_route_id` 必须存在。

生产容器中应通过 `ROUTER_CONFIG=/data/config/routes.yaml` 指向挂载配置。本地开发未设置 `ROUTER_CONFIG` 时，默认读取仓库内 `config/routes.yaml`。

## 验证

基础测试：

```bash
uv run python -m pytest -q
uv run python scripts/eval_routes.py --mock-embeddings
uv run python scripts/verify_route_contract.py
```

生产前 sidecar preflight：

```bash
uv run python scripts/preflight.py --router-base-url http://127.0.0.1:4001
```

LiteLLM 入口 E2E：

```bash
uv run python scripts/e2e_litellm_entry.py --litellm-base-url http://127.0.0.1:4000
```

这两个脚本需要 `LITELLM_MASTER_KEY` 或 `--api-key`，不会打印密钥或 prompt。

## 日志审计

IntentMux 有两个日志面：

- stdout：实时运行日志，便于 `docker logs` 和运行环境采集；
- audit JSONL：可选持久审计日志，写入 `ROUTER_AUDIT_LOG_DIR`，默认生产路径是 `/data/logs/routes/YYYY-MM-DD.jsonl`。

IntentMux 只统计结构化 JSON 路由日志：

- `route_complete`
- `route_error`

日志字段包括：

- `route_id`
- `target_model`
- `policy_id`
- `reason`
- `request_id`
- `request_id_source`
- `stream`
- `upstream_status`
- `ok`
- `outcome`
- `decision_ms`
- `upstream_ms`
- `upstream_headers_ms`（流式请求）
- `upstream_body_ms`（流式请求）

不会记录 prompt、completion、token usage 或 bearer token。`request_id` 只用于跨层关联，可能来自请求头、`metadata.semantic_router_request_id`、`user` 字段，或由 IntentMux 生成。

`event` 表示请求处理生命周期，`ok/outcome` 表示路由健康。上游非 2xx 会记录 `ok=false` 与 `outcome=upstream_non_200`，即使响应仍按代理语义返回给客户端。

阶段耗时字段用于定位慢请求：`decision_ms` 表示路由决策耗时，包含 hard rule / embedding 路径；`upstream_ms` 表示等待 LiteLLM / 下游模型的总耗时；流式请求额外记录 `upstream_headers_ms` 和 `upstream_body_ms`，用于区分首包慢还是响应体生成慢。

12 小时窗口 summary：

```bash
docker logs --since 12h intentmux 2>&1 \
  | uv run python scripts/router_log_summary.py --slow-request-limit 10
```

持久审计文件 summary：

```bash
uv run python scripts/router_log_summary.py /data/logs/routes/*.jsonl \
  --slow-request-limit 10
```

summary 会输出路由/目标/原因分布、`ok/outcome` 分布、上游状态码、`max_duration_ms`、`p50/p90/p95/p99` 延迟分位数，以及最慢请求 top N。慢请求列表只包含可审计元数据：时间、`request_id`、`route_id`、`target_model`、`reason`、`upstream_status` 和耗时。

route-error budget gate：

```bash
docker logs --since 12h intentmux 2>&1 \
  | uv run python scripts/check_route_error_budget.py \
      --min-total 1 \
      --max-error-rate 0 \
      --max-target-error-rate 0 \
      --max-route-error-rate 0 \
      --max-not-ok-rate 0 \
      --max-embedding-error-rate 0 \
      --max-upstream-status-rate 400=0
```

持久审计文件 budget gate：

```bash
uv run python scripts/check_route_error_budget.py /data/logs/routes/*.jsonl \
  --min-total 1 \
  --max-error-rate 0 \
  --max-target-error-rate 0 \
  --max-route-error-rate 0 \
  --max-not-ok-rate 0 \
  --max-embedding-error-rate 0
```

`embedding_error` 不一定会导致请求失败，它表示 embedding 不可用后按配置降级到 fast 路由；生产巡检应给它独立预算。若要放宽预算，可以用 `--max-embedding-error-rate 0.02` 这类阈值保留告警能力。

配置 + 日志诊断摘要：

```bash
uv run python scripts/diagnose_router_state.py \
  --routes config/routes.yaml \
  --logs /path/to/router-logs.ndjson
```

## 决策预览

不转发到 LiteLLM，只看会怎么路由：

```bash
curl http://127.0.0.1:4001/v1/semantic-router/decision \
  -H "Content-Type: application/json" \
  -d '{"model":"semantic-router","messages":[{"role":"user","content":"这个线上 bug 为什么偶发？"}]}'
```

返回内容包含 `route_id`、`target_model`、`policy_id`、`reason`、`rewrite` 和分数。

## 语义资产

运行时保持轻依赖。更大的 route bank 从 `config/route_sources.yaml` 声明的来源离线生成，不把 Hugging Face 等构建依赖带进运行时。
来源选择和语料政策见 [docs/router_quality_research.md](docs/router_quality_research.md)：默认不使用自生成语料，只使用成熟公开数据源和脱敏生产 review 样本。

```bash
uv sync --group assets
uv run python scripts/build_route_bank.py
uv run python scripts/build_eval_bank.py --per-route-limit 100
```

生成文件默认不进 git。生产 review 样本必须先脱敏，再导入 eval：

```bash
uv run python scripts/import_review_samples.py \
  --input data/source_samples/production_review.redacted.jsonl \
  --output data/semantic_sets/production_review_eval_cases.yaml \
  --routes config/routes.yaml
```

每条 JSONL 必须设置 `redacted: true`，并用 route id 作为 `expect`。

生产变更必须先通过 [docs/production_rollout_gate.md](docs/production_rollout_gate.md)，不要在探索阶段直接重启或重建生产 sidecar。

## 运行行为

推荐把 IntentMux 作为 LiteLLM compose project 里的并列 sidecar，而不是塞进 LiteLLM 挂载目录或服务内部。

- Docker health 使用 `/health`，避免 readiness 抖动触发重启循环。
- `/ready` 检查 router、LiteLLM、embedding 三层。
- embedding 不可用时，聊天请求 fail-open 到 `fallback_route_id`，并记录 `reason=embedding_error`。
- LiteLLM/upstream `5xx` 或连接异常 fail-closed 为脱敏 `502`，并记录 `route_error`。
- LiteLLM/upstream `4xx` 默认按代理语义透传，但审计日志记录 `ok=false` / `outcome=upstream_non_200`。

## 当前能力

IntentMux 已具备基本路由、preflight、LiteLLM-entry E2E、结构化日志和 error-budget gate，适合在本地或私有网关环境中做轻量意图分流验证。
