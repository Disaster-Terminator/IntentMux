# Cynosure Router

> 面向 LLM Gateway 的意图分流控制面。  
> Intent-aware routing sidecar for LiteLLM / OpenAI-compatible gateways.

Cynosure Router 是一个轻量、本地优先、可审计的 LLM 路由 sidecar。它不替代 LiteLLM，也不重新发明模型网关；它只负责在请求进入模型执行层之前，根据用户意图选择合适的模型通道，并把语义入口模型改写为部署环境里的真实目标模型。

当前项目主要面向中文-heavy 的个人 / 小团队 agent 流量，例如代码审查、debug、架构分析、线上故障判断、模型探活、低风险问答和混合自动化工作流。

---

## 为什么需要它

很多通用 LLM router 更关注英文 benchmark、强弱模型成本优化，或者直接把路由、评估、服务、执行层打包成一套重系统。

但在本地 LiteLLM 网关场景里，真正的问题通常更具体：

- 中文技术请求经常被低估复杂度；
- 简单闲聊、翻译、格式转换不应该消耗强模型额度；
- 代码审查、线上故障、架构权衡、权限安全类问题必须进强模型；
- 免费端点、实验模型、探活请求应该进入隔离通道；
- 路由决策必须能解释、能回放、能统计，而不是黑盒；
- LiteLLM 仍然应该保留 provider order、fallback、cooldown、key 管理和真实执行层职责。

Cynosure Router 的定位就是：**在 LiteLLM 前面增加一层可控、可观测、中文友好的意图分流层。**

---

## 核心定位

```text
Client / Agent / IDE / Automation
        │
        │ OpenAI-compatible request
        ▼
Cynosure Router
  - 读取 latest user message
  - 支持显式 route metadata
  - 支持中文 hard rules
  - 使用 embedding 做语义匹配
  - 低置信度安全回退
  - 改写 model 字段
  - 记录结构化路由日志
        │
        │ rewritten model
        ▼
LiteLLM Gateway
  - provider order
  - fallback
  - cooldown
  - auth / key management
  - actual model execution
        │
        ▼
Model Providers
```

Cynosure Router 只做路由决策和 `model` rewrite。真实模型调用、密钥、provider fallback 和供应商编排仍然交给 LiteLLM。

---

## 当前能力

### OpenAI-compatible Chat Proxy

支持：

- `POST /v1/chat/completions`
- 非流式响应
- `stream=true` SSE 流式响应
- 仅改写请求中的 `model` 字段
- 保留上游 LiteLLM 响应体
- 注入路由观测 headers

示例 headers：

```text
x-router-request-id
x-router-target-model
x-router-reason
```

### 语义入口模型

客户端请求一个语义入口模型，例如：

```json
{
  "model": "semantic-router",
  "messages": [
    {
      "role": "user",
      "content": "帮我审一下这个 PR 有没有竞态问题"
    }
  ]
}
```

Cynosure Router 会把它改写成真实目标模型，例如：

```text
pro-router
```

其他非入口模型会原样透传，不进入语义路由。LiteLLM 原生的 `smart-router` 也被刻意保留为单独的上游模型组，避免概念混淆。

### Route 抽象

默认示例 route：

| route_id | 目标模型示例 | 用途 |
|---|---|---|
| `fast` | `cheap-router` | 普通问答、解释、翻译、轻量总结 |
| `strong` | `pro-router` | 代码、debug、架构、多步推理、高风险判断 |
| `experimental` | `free-probe-router` | 免费端点探活、实验模型试探、低价值样例比较 |

这些目标模型只是当前 LiteLLM 部署里的示例名字。真正的目标模型由 `config/routes.yaml` 映射决定。

### 决策优先级

一次 routed 请求的决策顺序：

1. 非入口模型：直接 passthrough；
2. `metadata.route` / `metadata.target_route` 显式指定 route；
3. 中文 hard rules 命中高风险关键词；
4. embedding 语义匹配；
5. 低置信度或 embedding 异常时回退到 `fallback_route_id`。

这使路由行为既能自动判断，也能被上层 agent / workflow 显式控制。

### 安全回退

Embedding 故障被视为可降级问题：

- `/ready` 会报告 embedding degraded；
- routed chat 请求不会直接失败；
- 请求会 fallback 到配置里的 `fallback_route_id`；
- 路由日志中记录 `reason=embedding_error`。

LiteLLM 或上游模型失败则不同：上游异常会被包装成受控的 `502`，并记录为 `route_error`。

---

## 本地运行

安装依赖：

```bash
uv sync
```

启动 router：

```bash
uv run python -m router.app
```

默认端口：

```text
Router:    http://127.0.0.1:4001
LiteLLM:   http://127.0.0.1:4000
Embedding: http://127.0.0.1:1234/v1/embeddings
```

---

## 容器运行

Router 带有 `Dockerfile`，建议作为 LiteLLM compose 项目的 sibling service 运行，而不是临时本地进程。

推荐形态：

```text
LiteLLM :4000
Cynosure Router :4001
LM Studio Embedding :1234
```

Compose service 通常需要：

- build context: `/home/raystorm/gateway/gateway-semantic-router`
- upstream LiteLLM URL: `http://litellm:4000`
- embedding URL from container to host LM Studio: `http://host.docker.internal:1234/v1/embeddings`
- exposed router port: `4001`
- optional generated semantic asset mount: `/home/raystorm/gateway/gateway-semantic-router/data/semantic_sets:/app/data/semantic_sets:ro`

当前仍然是第三方 sidecar。未来可以更紧密地绑定 LiteLLM service readiness / restart lifecycle，但这是 roadmap 项，不是当前行为。

---

## 配置

主配置文件：

```text
config/routes.yaml
```

关键配置：

```yaml
route_model: semantic-router
fallback_route_id: fast
threshold: 0.55
margin: 0.04

embedding_url: http://127.0.0.1:1234/v1/embeddings
embedding_model: text-embedding-jina-embeddings-v5-text-small-retrieval@q8_0

litellm_base_url: http://127.0.0.1:4000
listen_host: 127.0.0.1
listen_port: 4001
```

环境变量覆盖：

```text
ROUTER_HOST
ROUTER_PORT
ROUTER_LITELLM_BASE_URL
ROUTER_LITELLM_TIMEOUT
ROUTER_EMBEDDING_URL
ROUTER_EMBEDDING_MODEL
ROUTER_ACCESS_LOG
ROUTER_READINESS_TIMEOUT
```

`ROUTER_ACCESS_LOG` 默认为 `false`。只有确实需要原始 HTTP access log 时才建议打开。

---

## 与 LiteLLM 的关系

Cynosure Router 是 LiteLLM 的旁路控制面，不是 LiteLLM fork。

两种接入方式：

### 方式一：客户端直接打 Router

客户端 base URL 指向：

```text
http://127.0.0.1:4001
```

请求：

```text
model=semantic-router
```

### 方式二：作为 LiteLLM model entry

低侵入生产方向是保留客户端 base URL 为 LiteLLM：

```text
http://127.0.0.1:4000
```

然后在 LiteLLM 中暴露一个模型入口，让 `model=semantic-router` 进入 sidecar。这样客户端只需要改 model，不需要改 base URL。

LiteLLM 的原生 `smart-router` 应保持独立：

- `smart-router`：LiteLLM 内置 complexity router；
- `semantic-router`：Cynosure Router 的语义任务路由入口。

当前证明和验收标准见：

```text
docs/superpowers/specs/2026-05-03-litellm-semantic-router-entry-design.md
```

---

## 健康检查

本地 liveness：

```bash
curl http://127.0.0.1:4001/health
```

分层 readiness：

```bash
curl http://127.0.0.1:4001/ready
```

`/ready` 会分别检查：

- router
- LiteLLM upstream
- embedding upstream

Docker health check 建议使用 `/health`，避免 embedding 或 LiteLLM 短暂 degraded 导致容器反复重启。`/ready` 更适合人工检查、部署门禁和运行状态观测。

---

## 决策预览

只查看路由决策，不转发到 LiteLLM：

```bash
curl http://127.0.0.1:4001/v1/semantic-router/decision \
  -H "Content-Type: application/json" \
  -d '{"model":"semantic-router","messages":[{"role":"user","content":"这个线上 bug 为什么偶发？"}]}'
```

返回内容包括：

- `source_model`
- `route_id`
- `target_model`
- `policy_id`
- `reason`
- `rewrite`
- `score`
- `second_score`

这个 endpoint 适合做 route 质量审查、灰度前验证、agent workflow 调试、eval case 复核，以及不消耗模型调用的 dry-run。

---

## 可观测性

每个 routed 请求都会写入结构化日志，例如：

```json
{
  "event": "route_complete",
  "request_id": "...",
  "request_id_source": "x-request-id",
  "source_model": "semantic-router",
  "route_id": "strong",
  "target_model": "pro-router",
  "policy_id": "embedding",
  "reason": "embedding",
  "rewrite": true,
  "stream": false,
  "upstream_status": 200,
  "score": 0.812341,
  "second_score": 0.421133,
  "duration_ms": 123.45
}
```

日志不会记录 prompt 或 bearer token。

Sidecar 会接受以下 request identity sources：

- `x-request-id`
- `x-correlation-id`
- W3C `traceparent`
- `metadata.semantic_router_request_id`
- `user`

最终 request id 会注入到上游 `x-request-id` header，方便 sidecar 到 LiteLLM 的跨层关联。

---

## 验证

基础测试：

```bash
uv run python -m pytest -q
uv run python scripts/eval_routes.py --mock-embeddings
```

CI 当前只运行基线自动化检查：

- `uv run python -m pytest -q`
- `uv run python scripts/eval_routes.py --mock-embeddings`

这套 CI 只证明基础行为没有回归，不宣称完整生产验证。Live preflight、LiteLLM-entry E2E、Docker log summary/review 和 route-error budget 仍然是 operator / local-production 检查。

---

## Production Preflight

对运行中的 router 做 preflight：

```bash
uv run python scripts/preflight.py \
  --router-base-url http://127.0.0.1:4001
```

需要设置：

```bash
export LITELLM_MASTER_KEY=...
```

也可以显式传入：

```bash
uv run python scripts/preflight.py \
  --router-base-url http://127.0.0.1:4001 \
  --api-key "$LITELLM_MASTER_KEY"
```

Preflight 会检查：

- `/health`
- `/ready`
- 非流式 chat route
- 流式 SSE route
- 路由 headers
- 基础响应形状

当 readiness degraded 时，脚本会打印 degraded component detail，例如：

```text
ready=False degraded=embedding:ConnectError
```

---

## LiteLLM Entry E2E

通过 LiteLLM 入口验证 `model=semantic-router`：

```bash
uv run python scripts/e2e_litellm_entry.py \
  --litellm-base-url http://127.0.0.1:4000
```

E2E 会验证：

- 非流式响应；
- 流式响应；
- sidecar route logs；
- 示例 `fast` / `strong` / `experimental` route；
- route id 与 configured target model 是否一致。

LiteLLM model-entry 路径目前不一定保留 client-supplied correlation id 到 sidecar，所以脚本会先尝试 request-id matching，再 fallback 到 recent route shape matching。

如果验证路径预期必须端到端保留 request id，可使用：

```bash
uv run python scripts/e2e_litellm_entry.py \
  --litellm-base-url http://127.0.0.1:4000 \
  --require-request-id-log-match
```

---

## Route Log Summary

从 sidecar 日志生成路由统计：

```bash
docker logs --since 12h gateway_semantic_router 2>&1 \
  | uv run python scripts/router_log_summary.py
```

摘要会统计：

- routed 请求总数；
- completed / error；
- stream / non-stream；
- route_id 分布；
- target_model 分布；
- reason 分布；
- error_type 分布；
- upstream_status 分布；
- 非 200 上游状态；
- 最大耗时；
- 被忽略的异常日志记录。

解析器会忽略 uvicorn access lines，只统计结构化 `route_complete` / `route_error` JSON 记录。Prompts 和 bearer tokens 不会进入日志。

---

## Route Error Budget

上线前或灰度后检查路由错误预算：

```bash
docker logs --since 12h gateway_semantic_router 2>&1 \
  | uv run python scripts/check_route_error_budget.py \
      --min-total 1 \
      --max-error-rate 0 \
      --max-target-error-rate 0 \
      --max-reason-rate embedding_error=0 \
      --max-upstream-status-rate 400=0
```

这个 gate 用来防止 router 看起来能跑，但实际已经出现：

- 某个 target 持续失败；
- embedding_error 过多；
- 上游返回大量 400 / 500；
- 日志结构漂移；
- eval 没覆盖到的线上异常。

脚本会输出稳定的 PASS / FAIL 报告，并在预算超限时返回非零 exit code。

---

## Streaming Smoke Test

```bash
curl -N http://127.0.0.1:4001/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"semantic-router","stream":true,"messages":[{"role":"user","content":"这个线上 bug 为什么偶发？只回答 OK"}],"max_tokens":8}'
```

---

## Semantic Assets

Runtime routing 保持 dependency-light。较大的 semantic assets 通过离线脚本生成，来源声明在：

```text
config/route_sources.yaml
```

当前 source manifest 包括：

- MASSIVE zh-CN / zh-TW official JSONL tarball，用于通用 assistant 与 utility utterances；
- SWE-bench issue statements，用于 repository-level software engineering tasks；
- MBPP 和 HumanEval，用于 code-generation prompts；
- local JSONL samples，用于 model-probe traffic。

构建依赖与 runtime 隔离：

```bash
uv sync --group assets
uv run python scripts/build_route_bank.py
uv run python scripts/build_eval_bank.py --per-route-limit 100
```

运行扩展 eval：

```bash
uv run python scripts/eval_routes.py \
  --cases data/semantic_sets/eval_bank.yaml
```

Runtime loading 是保守的：`config/routes.yaml` 声明 `route_bank_path: data/semantic_sets/route_bank.yaml`，`load_settings()` 仅在文件存在时合并 generated bank 和 checked-in seed utterances。没有生成资产时，router 继续使用 seed routes。

### Redacted Production Samples

可把脱敏生产 review 样例提升为 eval cases：

```bash
uv run python scripts/import_review_samples.py \
  --input data/source_samples/production_review.redacted.jsonl \
  --output data/semantic_sets/production_review_eval_cases.yaml

uv run python scripts/build_eval_bank.py \
  --manual-cases data/semantic_sets/production_review_eval_cases.yaml \
  --per-route-limit 100
```

每条 JSONL sample 必须：

- `redacted: true`
- 包含 `text`
- `expect` 指向已配置 route id，例如 `fast` 或 `strong`

Importer 默认拒绝未脱敏样例。

---

## 项目边界

Cynosure Router 不做这些事：

- 不保存 API key；
- 不管理 provider order；
- 不实现 provider fallback；
- 不替代 LiteLLM；
- 不记录原始 prompt；
- 不提交 LiteLLM mount、tokens 或 `.env`；
- 不追求训练一个通用 LLM router 模型；
- 不把 route 质量伪装成不可解释黑盒。

它只做：

```text
intent → route_id → target_model → auditable rewrite
```

本仓库仍然应与 `/home/raystorm/gateway/litellm` 保持隔离。不要把本地 LiteLLM mount 文件、tokens、`.env` 或供应商密钥材料加入这里。

---

## 当前状态

项目处于本地生产化打磨阶段，尚未 public-release ready。公开发布前还需要统一审计：

- configurable route abstraction；
- observability contract；
- redacted eval workflow；
- license 与 release documentation；
- README / GitHub metadata / repository name 的最终一致性。

已经具备：

- OpenAI-compatible chat proxy；
- streaming / non-streaming 转发；
- 配置化 route；
- 显式 route metadata；
- 中文 hard rules；
- embedding semantic match；
- readiness / liveness；
- decision preview；
- structured route logs；
- route summary；
- route error budget gate；
- mock eval；
- preflight；
- Docker sidecar 运行形态。

仍需继续打磨：

- 更严格的 LiteLLM model-entry E2E；
- 更完整的 route bank 生成和审查流程；
- 基于真实 redacted 样例的 eval 扩充；
- 生命周期耦合策略；
- 公共发布前的 license / release 文档整理。

---

## Name

Cynosure 的含义是“指引方向的中心点”。这个名字对应本项目的职责：不执行模型、不替代网关，而是在模型流量进入执行层前，给出可解释、可审计、可回退的方向选择。

```text
Cynosure Router
= the guiding point for model traffic
```

GitHub 仓库标题、描述、重命名等平台元数据建议不在本 PR 中直接修改；建议先作为文件记录进入 review。详见：

```text
docs/PROJECT_IDENTITY.md
```
