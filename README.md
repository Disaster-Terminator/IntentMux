# IntentMux

> 轻量、可审计的 LiteLLM 意图分流 sidecar。<br>
> 按请求意图选择 `route_id`，再映射到你的本地 LiteLLM 模型组。

[English](README.en.md)

| 项目 | 内容 |
| --- | --- |
| 用途 | 在 LiteLLM / OpenAI-compatible gateway 前做轻量意图分流 |
| 接入面 | 客户端保持打 LiteLLM，只把模型名切到 `semantic-router` |
| 路由模型 | `semantic-router` 是兼容入口名；产品名是 IntentMux |
| 决策输出 | `route_id -> target_model`，例如 `strong -> pro-router` |
| 可审计性 | 结构化 `route_complete` / `route_error` 日志，不记录 prompt 或 bearer token |
| 运行状态 | 本地生产验证中；暂不按 public-release 项目发布 |

IntentMux 不是模型提供商，也不是 LiteLLM 的替代品。它是一个本地优先的
routing sidecar：只改写进入 sidecar 的请求 `model` 字段，把
`model=semantic-router` 路由到配置里的 `route_id`，再解析到实际部署中的
`target_model`。其他模型名默认透传给 LiteLLM。

当前示例配置使用 `fast`、`strong`、`experimental` 三个产品级 route id，并映射到本机
LiteLLM 模型组 `cheap-router`、`pro-router`、`free-probe-router`。这些
`target_model` 是部署名，不是产品接口。

本仓库和 `/path/to/gateway/litellm` 保持边界清晰。不要把 LiteLLM
挂载目录、token、`.env` 或 provider 凭据加入本仓库。

## 适合什么场景

- 你已经有 LiteLLM / OpenAI-compatible gateway。
- 你想用很小的接入成本，把一部分请求按意图分到不同模型组。
- 你希望路由决策可回放、可审计、可用日志继续改进。
- 你不想引入一个大型调度平台，也不想让客户端大改端点。

IntentMux 的差异化不是“再造一个复杂 router”，而是轻量、本地、快速部署、日志可读。
成熟的 provider 路由、fallback、限流和鉴权仍交给 LiteLLM。

## 快速运行

```bash
uv run python -m router.app
```

默认端点：

- IntentMux sidecar: `http://127.0.0.1:4001`
- LiteLLM upstream: `http://127.0.0.1:4000`
- Embedding upstream: `http://127.0.0.1:1234/v1/embeddings`

环境变量：

- `ROUTER_HOST`
- `ROUTER_PORT`
- `ROUTER_LITELLM_BASE_URL`
- `ROUTER_LITELLM_TIMEOUT`
- `ROUTER_EMBEDDING_URL`
- `ROUTER_EMBEDDING_MODEL`
- `ROUTER_ACCESS_LOG`
- `ROUTER_READINESS_TIMEOUT`

## LiteLLM 接入方式

低侵入接入方式是：客户端继续请求 LiteLLM `:4000`，只把模型名切到
`semantic-router`。

```text
client -> LiteLLM :4000, model=semantic-router
       -> IntentMux :4001
       -> route_id
       -> target_model
       -> LiteLLM model group
```

`semantic-router` 是兼容入口名，不等于项目品牌名。项目叫 IntentMux；入口名保留
`semantic-router`，是为了降低现有部署迁移成本。

LiteLLM 原生 `smart-router` 应保持独立：它仍表示 LiteLLM 的 complexity router；
IntentMux 的 `semantic-router` 表示本项目的意图分流入口。

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

运行时校验会阻止递归配置：入口模型本身不能作为 route id 或 target model，
`fallback_route_id` 必须存在。

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

不会记录 prompt 或 bearer token。

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

运行时保持轻依赖。更大的 route bank 从 `config/route_sources.yaml` 声明的来源离线生成，
不把 Hugging Face 等构建依赖带进运行时。

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

推荐把 IntentMux 作为 LiteLLM compose project 里的并列 sidecar，而不是塞进
LiteLLM 挂载目录或服务内部。

当前行为：

- Docker health 使用 `/health`，避免 readiness 抖动触发重启循环。
- `/ready` 检查 router、LiteLLM、embedding 三层。
- embedding 不可用时，聊天请求 fail-open 到 `fallback_route_id`，并记录
  `reason=embedding_error`。
- LiteLLM/upstream `5xx` 或连接异常 fail-closed 为脱敏 `502`，并记录
  `route_error`。

未来是否把 sidecar 生命周期更强地绑定到 LiteLLM 本体服务，是单独的设计项，不在当前
运行时里隐式实现。

## 项目状态

IntentMux 当前服务真实本地需求，已具备基本路由、preflight、E2E、结构化日志和
error-budget gate。仓库仍处于生产验证和文档打磨阶段，许可证、public-release 文档、
本地路径统一和发布包装会在稳定后再处理。
