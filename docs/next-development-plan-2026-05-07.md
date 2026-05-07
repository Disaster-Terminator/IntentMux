# IntentMux 下一步开发计划：审计优先与执行层候选

日期：2026-05-07
状态：本轮已执行运行时配置与审计日志基线；execution candidates 仍未实现
范围：IntentMux 仓库；不改 LiteLLM 源码；不要求客户端大改端点

## 背景

LiteLLM 止血后，`semantic-router` 链路已经恢复可用。当前项目的核心语义路由能力已经能在生产链路中工作：

```text
client -> LiteLLM semantic-router model group -> IntentMux sidecar -> LiteLLM target model/group
```

但日志复盘暴露出两个更基础的问题：

- 项目没有自己的持久审计日志，跨容器重启后无法完整复盘；
- 当前容器镜像把 `config/routes.yaml` COPY 进 `/app/config`，运行时没有挂载用户配置；
- IntentMux 仍把执行层 fallback 交给 LiteLLM group，遇到 LiteLLM group/fallback bug 时只能观察，不能主动恢复。

因此下一步开发不应直接“猜策略”，而应先让日志变成稳定资产，再实现最小的执行层候选能力。

## 调研依据

- LiteLLM 官方 Docker 示例通过 `-v $(pwd)/litellm_config.yaml:/app/config.yaml`
  或 compose `./litellm-config.yaml:/app/config.yaml` 挂载配置。IntentMux 作为 LiteLLM
  下游 sidecar，也应把用户配置放在运行目录/挂载卷，而不是只 COPY 到镜像。
- 十二要素原则建议应用把事件流写到 stdout，由运行环境收集；这适合作为容器观测默认面。
- Docker 官方说明默认 `json-file` logging driver 不做轮转，生产更推荐带轮转的 `local`
  driver 或显式 log options。因此业务审计不能只依赖 `docker logs` 的当前生命周期。

结论：IntentMux 应采用“双日志面”：

- stdout：保留实时运行日志，符合容器习惯；
- audit JSONL：写入用户挂载的 IntentMux home，用于跨重启复盘和产品改进。

## 目标

让 IntentMux 从“可运行的语义分流 sidecar”推进到“可审计、可复盘、能主动避开坏执行候选的轻量本地路由器”。

## 非目标

- 不改 LiteLLM 源码；
- 不重写 LiteLLM 的 provider 执行、鉴权、监控能力；
- 不强迫用户迁移到新端点；
- 不在这一轮实现完整 provider router；
- 不把 prompt 或 bearer token 写入日志；
- 不在缺少日志证据时调整 embedding 阈值或 route bank。

## 产品形态：LiteLLM 下游 sidecar

IntentMux 的用户不是从零部署一个全新网关，而是已经有 LiteLLM，并希望用很低侵入方式增加一个语义分流入口。因此推荐形态是：

```text
litellm/
  docker-compose.yml
  config.yaml
  .env
  intentmux/
    config/
      routes.yaml
    semantic_sets/
      route_bank.yaml
    logs/
      routes/
        2026-05-07.jsonl
    reviews/
      redacted-samples.jsonl
```

容器内部对应：

```text
/app
  router code and packaged defaults
/data
  config/routes.yaml
  semantic_sets/route_bank.yaml
  logs/routes/YYYY-MM-DD.jsonl
  reviews/*.jsonl
```

推荐 compose 片段：

```yaml
services:
  intentmux:
    image: ghcr.io/<owner>/intentmux:<version>
    restart: unless-stopped
    volumes:
      - ./intentmux:/data
    environment:
      ROUTER_CONFIG: /data/config/routes.yaml
      ROUTER_AUDIT_LOG_DIR: /data/logs/routes
      ROUTER_LITELLM_BASE_URL: http://litellm:4000
      ROUTER_EMBEDDING_URL: http://host.docker.internal:1234/v1/embeddings
```

设计口径：

- `/app` 是镜像内容，不是用户运行时状态；
- `/data` 是用户可备份、可迁移、可审计的运行时目录；
- `config/routes.yaml`、`semantic_sets/route_bank.yaml`、`logs/routes/*.jsonl`
  都属于同一个 IntentMux home；
- 不把 LiteLLM 的 config、secrets 或 DB 纳入 IntentMux home；
- 本地非容器运行时，`ROUTER_CONFIG` 可指向任意 routes 文件，`ROUTER_AUDIT_LOG_DIR`
  可指向 repo 外目录；开发模式继续允许使用仓库内 `config/routes.yaml`。

## 开发方向一：运行时配置外置

### 问题

当前 Dockerfile 执行：

```dockerfile
COPY config ./config
```

本机 compose 只挂载：

```yaml
../gateway-semantic-router/data/semantic_sets:/app/data/semantic_sets:ro
```

这意味着 routes 配置默认来自镜像内 `/app/config/routes.yaml`。用户修改路由、阈值、目标模型、route bank 路径时，要么改源码目录并重建镜像，要么依赖不清晰的覆盖方式。

### 设计

新增 `ROUTER_CONFIG` 环境变量：

```text
ROUTER_CONFIG=/data/config/routes.yaml
```

加载顺序：

1. 如果设置 `ROUTER_CONFIG`，从该路径读取；
2. 否则使用当前兼容默认 `config/routes.yaml`；
3. 如果 `ROUTER_CONFIG` 指向不存在的文件，启动失败并给出明确错误。

同时提供示例运行目录：

```text
examples/intentmux-home/
  config/routes.yaml
  semantic_sets/route_bank.yaml
```

`route_bank_path` 推荐写成相对 routes 文件的路径：

```yaml
route_bank_path: ../semantic_sets/route_bank.yaml
```

### 验收

- Docker/本地都能用 `ROUTER_CONFIG` 指定配置；
- 未设置 `ROUTER_CONFIG` 时，现有开发命令不变；
- 配置文件不存在时启动失败，错误信息包含路径；
- 文档明确 `/app` 与 `/data` 的职责；
- 本机 compose 可改为挂载 `../gateway-semantic-router-runtime:/data` 或
  `./intentmux:/data`，而不是只挂载 semantic sets。

## 开发方向二：项目级审计日志

### 问题

当前 IntentMux 依赖 Docker stdout。容器重启后，项目无法回答：

- 某个 commit 之后实际发生了多少请求；
- 哪些 route / target / reason 出过非 200；
- 某个 upstream 400/5xx 是否持续存在；
- 延迟劣化是否集中在某个 target；
- 一次产品调整前后是否真的改善。

### 设计

新增 IntentMux 自己掌控的 JSONL 审计日志落盘，默认路径可配置，例如：

```text
/data/logs/routes/YYYY-MM-DD.jsonl
```

每条记录继续保持当前结构化字段，并补齐分析需要的最小字段：

```json
{
  "event": "route_complete",
  "ts": "2026-05-07T06:36:51.123Z",
  "request_id": "semantic-e2e-...",
  "source_model": "semantic-router",
  "route_id": "fast",
  "policy_id": "low_confidence",
  "reason": "low_confidence",
  "target_model": "cheap-router",
  "stream": true,
  "upstream_status": 400,
  "duration_ms": 10752.86,
  "score": 0.366368,
  "second_score": 0.194134
}
```

日志要求：

- append-only JSONL；
- 默认按天分文件；
- 支持环境变量关闭或改路径：
  - `ROUTER_AUDIT_LOG_DIR=/data/logs/routes`
  - `ROUTER_AUDIT_LOG_ENABLED=true`
- 文件权限不应公开敏感信息；
- 继续做 prompt / authorization redaction；
- stdout 仍保留，便于 Docker 观测；
- 分析脚本优先支持读取文件，也支持 stdin。

### 验收

- 重启容器后，旧审计日志仍存在；
- `router_log_summary.py` 可直接分析本地文件；
- `check_route_error_budget.py` 可直接分析本地文件；
- 新增测试证明 prompt 与 bearer token 不会落盘；
- 新增 E2E 或集成测试证明真实请求会写入审计文件；
- 文档说明生产挂载建议。

## 开发方向三：把上游非 200 升级为一等审计信号

### 问题

当前窗口出现：

```text
route_complete + upstream_status=400
```

脚本能通过 `upstream_status` 预算捕获，但事件名会误导人以为“全部成功”。

同时当前代码中 `is_upstream_failure(status_code)` 只把 `>=500` 视为失败，导致上游 400 会走 `route_complete`。这在“代理透明返回”意义上可以解释，但在“路由健康审计”意义上不够直接。

### 设计

保留现有 `route_complete` 兼容性，同时新增更明确字段：

```json
{
  "outcome": "upstream_non_200",
  "ok": false
}
```

建议口径：

- `ok=true`：上游 2xx；
- `ok=false`：上游非 2xx、超时、协议错误、IntentMux 内部错误；
- `event` 继续表达请求处理生命周期；
- `outcome` 表达业务健康。

### 验收

- 非 200 请求在 summary 中单独显示；
- budget 默认可以按 `ok=false` 失败；
- 旧日志无 `ok/outcome` 时仍能兼容解析；
- README/runbook 解释 `event` 与 `outcome` 的区别。

## 开发方向四：执行层候选模型列表

### 问题

当前配置把 route 映射到单个 `target_model`：

```yaml
routes:
  strong:
    target_model: pro-router
```

这让 IntentMux 依赖 LiteLLM group 继续做候选选择。一旦 LiteLLM 的 group/fallback/pre-call 组合出问题，IntentMux 没有自己的候选尝试能力。

### 设计

兼容旧配置，新增候选列表：

```yaml
routes:
  strong:
    target_model: pro-router
    targets:
      - model: opencode-go/deepseek-v4-pro
        label: primary
      - model: deepseek-ai/DeepSeek-V4-Pro
        label: fallback
      - model: cheap-router
        label: last-resort
```

执行策略：

- 默认仍使用 `target_model`，不改变现有行为；
- 当 route 配置了 `targets` 且启用候选执行时，按顺序尝试；
- 候选失败只针对明确可重试的失败：
  - upstream 429；
  - upstream 5xx；
  - timeout；
  - network/protocol error；
- 400 默认不自动 fallback，除非明确配置，因为 400 可能代表请求形态不兼容；
- 每次候选尝试都写入审计日志。

日志字段：

```json
{
  "route_id": "strong",
  "selected_target_model": "deepseek-ai/DeepSeek-V4-Pro",
  "candidate_count": 3,
  "candidate_index": 1,
  "candidate_label": "fallback",
  "fallback_reason": "upstream_5xx",
  "attempt": 2
}
```

### 验收

- 单值 `target_model` 配置完全兼容；
- 候选列表配置可通过 contract 校验；
- 第一个候选 5xx 时能尝试第二个；
- 第一个候选 400 时默认不尝试第二个；
- 所有尝试有审计日志；
- E2E 能证明客户端仍只打原入口，不需要换端点。

## 推荐实施顺序

1. 已完成：外置运行时配置，新增 `ROUTER_CONFIG`，明确 `/app` 与 `/data` 边界。
2. 已完成：整理 compose/部署文档，当前本机使用 `/path/to/intentmux-runtime:/data`。
3. 已完成：实现项目级审计日志落盘。
4. 已完成：升级日志分析脚本，使文件输入、`ok/outcome` 预算进入工作流。
5. 已完成首轮：用新日志跑本机真实生产 E2E 窗口。
6. 未开始：等待真实流量继续积累后，确认 `low_confidence`、非 200、长延迟是否稳定复现。
7. 未开始：写 execution candidates 的详细实现计划。
8. 未开始：实现候选模型列表和有限 fallback。
9. 未开始：再讨论是否调整 route bank、阈值、产品文档与 public 发布。

## 建议下一轮 goal

在不改 LiteLLM 源码、不实现执行层候选模型的前提下，先把 IntentMux 的运行时形态和生产审计能力做成可靠基线：

```text
按 LiteLLM 下游 sidecar 的部署形态重构 IntentMux 运行时边界：新增 ROUTER_CONFIG 支持外置 routes 配置，约定 /data 为用户挂载的 IntentMux home；增加持久 JSONL 审计日志与文件输入分析能力；把 upstream 非 2xx 从普通 route_complete 中提升为可预算的健康信号；保留现有 stdout、默认开发配置与客户端入口兼容；用测试和本机真实 E2E 验证配置外置、重启后日志可复盘。
```

## 已收敛的默认选择

- 审计日志默认开启，但仅在 `ROUTER_AUDIT_LOG_DIR` 可写时落盘；不可写时启动失败，避免用户以为有审计但实际没有。
- 默认容器日志路径是 `/data/logs/routes`。
- 默认容器配置路径通过 `ROUTER_CONFIG=/data/config/routes.yaml` 显式指定；镜像内 `config/routes.yaml` 只作为开发/示例兼容。
- 非 2xx 引入 `ok/outcome`，summary 与 budget 默认把 `ok=false` 视为健康失败。
- 下一轮只做运行时配置与审计日志，不做 execution candidates。

## 2026-05-07 本机执行结果

本机生产运行时目录：

```text
/path/to/intentmux-runtime
  config/routes.yaml
  semantic_sets/route_bank.yaml
  logs/routes/2026-05-07.jsonl
  reviews/
```

本机 LiteLLM compose 变更：

- `gateway-semantic-router` 挂载 `../intentmux-runtime:/data`
- 设置：
  - `ROUTER_CONFIG=/data/config/routes.yaml`
  - `ROUTER_AUDIT_LOG_ENABLED=true`
  - `ROUTER_AUDIT_LOG_DIR=/data/logs/routes`

备份：

```text
/path/to/docker-compose.yml.backup-20260507-intentmux-runtime
```

验证证据：

- route contract：PASS
- mock eval：10/10 PASS
- unit tests：179 passed, 1 warning
- sidecar `/health`：200
- sidecar `/ready`：200
- LiteLLM-entry E2E：PASS，覆盖 `strong/fast/experimental`
- sidecar restart 后 `/ready`：200
- restart 后旧审计 JSONL 仍可读
- 审计文件当前 10 行：

```text
total=10 completed=10 errors=0 streams=3 nonstreams=7
routes: experimental=2, fast=2, strong=6
targets: cheap-router=2, free-probe-router=2, pro-router=6
reasons: embedding=4, hard_rule:线上=6
error_types: none
outcomes: success=10
not_ok=0
upstream_statuses: 200=10
upstream_non_200: none
max_duration_ms=15995.15
```

budget：

```text
PASS route_error_budget
total=10 completed=10 errors=0 error_rate=0.0000 not_ok=0 not_ok_rate=0.0000
```

敏感字段检查：

```text
敏感 prompt / Bearer / authorization / request_body / raw_body: 0 命中
```

## 后续仍需人工确认的产品边界

只有一个边界需要用户拍板：本机生产目录名是否采用 `intentmux/`，还是继续沿用当前
`gateway-semantic-router/` 路径。代码和文档可以同时支持两者，但 public 文档应只推荐一个名字。
