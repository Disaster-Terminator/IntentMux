# IntentMux

> 轻量、可审计的 LiteLLM 意图分流 sidecar。<br>
> 按请求意图选择 `route_id`，再映射到你的本地 LiteLLM 模型组。

<p align="center">
  <img alt="status: local validation" src="https://img.shields.io/badge/status-local_validation-f59e0b?style=for-the-badge">
  <img alt="entry: semantic-router" src="https://img.shields.io/badge/entry-semantic--router-2563eb?style=for-the-badge">
  <img alt="gateway: LiteLLM compatible" src="https://img.shields.io/badge/gateway-LiteLLM_compatible-16a34a?style=for-the-badge">
  <img alt="logs: no prompts or tokens" src="https://img.shields.io/badge/logs-no_prompts_or_tokens-7c3aed?style=for-the-badge">
</p>

[English](README.en.md)

## 一句话

IntentMux 是一个本地优先的 OpenAI-compatible / LiteLLM-compatible 路由 sidecar：客户端仍然请求原来的 LiteLLM 入口，只把模型名切到 `semantic-router`，IntentMux 根据请求意图选择 `route_id`，再映射到实际部署中的 `target_model`。

<table>
  <tr>
    <td><strong>意图分流</strong><br>从请求内容判断 `fast` / `strong` / `experimental` 等 route id。</td>
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

当前示例配置使用 `fast`、`strong`、`experimental` 三个产品级 route id，并映射到本机 LiteLLM 模型组 `cheap-router`、`pro-router`、`free-probe-router`。这些 `target_model` 是部署名，不是产品接口。

本仓库和 `/home/raystorm/gateway/litellm` 保持边界清晰。不要把 LiteLLM 挂载目录、token、`.env` 或 provider 凭据加入本仓库。

## 适合什么场景

- 你已经有 LiteLLM / OpenAI-compatible gateway。
- 你想用很小的接入成本，把一部分请求按意图分到不同模型组。
- 你希望路由决策可回放、可审计、可用日志继续改进。
- 你不想引入一个大型调度平台，也不想让客户端大改端点。

IntentMux 的差异化不是“再造一个复杂 router”，而是轻量、本地、快速部署、日志可读。成熟的 provider 路由、fallback、限流和鉴权仍交给 LiteLLM。

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

- `ROUTER_HOST`
- `ROUTER_PORT`
- `ROUTER_LITELLM_BASE_URL`
- `ROUTER_LITELLM_TIMEOUT`
- `ROUTER_EMBEDDING_URL`
- `ROUTER_EMBEDDING_MODEL`
- `ROUTER_ACCESS_LOG`
- `ROUTER_READINESS_TIMEOUT`

## LiteLLM 接入方式

低侵入接入方式是：客户端继续请求 LiteLLM `:4000`，只把模型名切到 `semantic-router`。

```text
client -> LiteLLM :4000, model=semantic-router
       -> IntentMux :4001
       -> route_id
       -> target_model
       -> LiteLLM model group
```

`semantic-router` 是兼容入口名，不等于项目品牌名。项目叫 IntentMux；入口名保留 `semantic-router`，是为了降低现有部署迁移成本。

LiteLLM 原生 `smart-router` 应保持独立：它仍表示 LiteLLM 的 complexity router；IntentMux 的 `semantic-router` 表示本项目的意图分流入口。

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

不会记录 prompt、completion、token usage 或 bearer token。`request_id` 只用于跨层关联，可能来自请求头、`metadata.semantic_router_request_id`、`user` 字段，或由 IntentMux 生成。

12 小时窗口 summary：

```bash
docker logs --since 12h gateway_semantic_router 2>&1 \
  | uv run python scripts/router_log_summary.py
```

route-error budget gate：

```bash
docker logs --since 12h gateway_semantic_router 2>&1 \
  | uv run python scripts/check_route_error_budget.py \
      --min-total 1 \
      --max-error-rate 0 \
      --max-target-error-rate 0 \
      --max-route-error-rate 0 \
      --max-reason-rate embedding_error=0 \
      --max-upstream-status-rate 400=0
```

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

## 生命周期

推荐把 IntentMux 作为 LiteLLM compose project 里的并列 sidecar，而不是塞进 LiteLLM 挂载目录或服务内部。

当前行为：

- Docker health 使用 `/health`，避免 readiness 抖动触发重启循环。
- `/ready` 检查 router、LiteLLM、embedding 三层。
- embedding 不可用时，聊天请求 fail-open 到 `fallback_route_id`，并记录 `reason=embedding_error`。
- LiteLLM/upstream `5xx` 或连接异常 fail-closed 为脱敏 `502`，并记录 `route_error`。

未来是否把 sidecar 生命周期更强地绑定到 LiteLLM 本体服务，是单独的设计项，不在当前运行时里隐式实现。

## 项目状态

IntentMux 当前服务真实本地需求，已具备基本路由、preflight、E2E、结构化日志和 error-budget gate。仓库仍处于生产验证和文档打磨阶段，许可证、public-release 文档、本地路径统一和发布包装会在稳定后再处理。
