# Next Step Plan: LiteLLM 止血后推进

日期：2026-05-07
范围：IntentMux / LiteLLM 本机生产验证
状态：已归档；任务一与当前可读窗口的任务二已完成，未完成项移入
`docs/next-development-plan-2026-05-07.md`

## 背景

2026-05-07 已完成一次 LiteLLM 止血：

- `router_settings.enable_pre_call_checks` 从 `true` 改为 `false`
- compose 中 `STORE_MODEL_IN_DB` 从 `"True"` 改为 `"False"`
- 只重启了 `litellm` 本体服务，未重启 `gateway_semantic_router`、db、prometheus
- `/model/info` 从 85 条双份记录恢复为 43 条 config-only 记录
- `semantic-router` 仍存在
- IntentMux sidecar preflight 通过
- LiteLLM-entry E2E 通过
- 止血后 LiteLLM 日志中 `LLM Provider NOT provided`、`This model isn't mapped yet`、
  `No fallback model group found` 增量为 0

当前结论：

- IntentMux 的语义分流链路有效；
- LiteLLM v1.83.14 的 `enable_pre_call_checks + custom OpenAI-compatible model +
  fallback/router group` 组合不可靠；
- 短期不应等待 LiteLLM 上游修复来恢复生产；
- 中期应降低 IntentMux 对 LiteLLM router group/fallback 的依赖。

## 问题一：LiteLLM timeout 配置可能未生效

LiteLLM 重启日志出现：

```text
Key 'request_timeout' is not a valid argument for Router.__init__(). Ignoring this key.
```

当前配置里有：

```yaml
router_settings:
  request_timeout: 45
```

compose 环境里还有：

```yaml
LITELLM_REQUEST_TIMEOUT: "45"
```

风险：

- `request_timeout` 可能完全没有作用；
- 多 deployment 链路失败时，真实等待时间可能不是我们以为的 45 秒；
- 这会直接影响 `pro-router` streaming `ReadTimeout` 和“死链延迟爆炸”问题；
- 贸然修改 timeout 字段可能影响正常长上下文请求，所以需要单独验证。

### 计划

1. 读取当前容器内 `/app/litellm/router.py`，确认 `Router.__init__()` 和
   `update_settings()` 接受的 timeout 字段。
2. 查 LiteLLM 官方文档或当前版本源码，确认 proxy/config 下应使用：
   - `router_settings.timeout`
   - `litellm_settings.request_timeout`
   - 环境变量 `LITELLM_REQUEST_TIMEOUT`
   - 或其他字段
3. 用最小配置变更验证启动日志：
   - 备份 `config.yaml` 与 `docker-compose.yml`
   - 将无效字段调整为当前版本真实接受的字段
   - 只重启 `litellm`
   - 确认 warning 消失
4. 跑验收：
   - `/model/info`
   - `opencode-go/deepseek-v4-pro`
   - `cheap-router`
   - `pro-router`
   - IntentMux preflight
   - LiteLLM-entry E2E
   - LiteLLM 错误增量检查

### 2026-05-07 执行结论

根因已确认：当前容器内 LiteLLM v1.83.14 的 `Router.__init__()` 接收
`timeout` 和 `stream_timeout`，不接收 `request_timeout`；proxy 启动时只把
`litellm.Router.get_valid_args()` 允许的字段传入 Router，所以
`router_settings.request_timeout` 会被明确忽略。

已执行的最小变更：

- 备份 `/path/to/gateway/litellm/config.yaml` 到
  `/path/to/gateway/litellm/config.yaml.backup-20260507-timeout-field`
- 将 `router_settings.request_timeout: 45` 改为 `router_settings.timeout: 45`
- 只重启 `litellm` 本体服务，未重启 `gateway_semantic_router`、db、prometheus

重启后验证结果：

- LiteLLM startedAt：`2026-05-07T06:36:28.740269488Z`
- `/health/readiness` 返回 200，db connected
- 启动日志不再出现 `request_timeout` / `Router.__init__` warning
- `/model/info` 返回 43 条，`db_model=false` 为 43 条，`db_model=true` 为 0 条
- IntentMux preflight 全部通过
- LiteLLM-entry E2E 全部通过：
  - `strong -> pro-router` 非流式 200
  - `strong -> pro-router` 流式 200
  - `fast -> cheap-router` 非流式 200
  - `experimental -> free-probe-router` 非流式 200
- IntentMux 重启后窗口结构化日志：
  - `total=6 completed=6 errors=0`
  - `routes: experimental=1, fast=1, strong=4`
  - `targets: cheap-router=1, free-probe-router=1, pro-router=4`
  - `upstream_statuses: 200=6`
- route error budget：PASS，`error_rate=0.0000`
- LiteLLM 重启后日志未命中：
  - `LLM Provider NOT provided`
  - `This model isn't mapped yet`
  - `No fallback model group found`

保留项：

- compose 中的 `LITELLM_REQUEST_TIMEOUT: "45"` 暂保留为 LiteLLM 全局默认，不作为
  Router 参数；当前 Router 级字段以 `router_settings.timeout` 为准。
- 尚未构造慢链路验证 45 秒实际截止时间；这应作为后续专门测试，而不是在生产止血窗口里
  人为打断真实请求。

### 验收标准

- LiteLLM 启动日志不再出现 `request_timeout` invalid argument warning；
- 正常请求不回退、不 400、不 5xx；
- IntentMux E2E 仍能看到 `strong/fast/experimental` 三档 route；
- 新日志中没有新增 `LLM Provider NOT provided`；
- 如果能构造慢/坏链路，实际超时符合预期范围。

## 问题二：止血后日志观察

止血只能证明当前 E2E 干净，不能证明长时间生产窗口稳定。

### 计划

在止血后的可用窗口、12h 和 24h 窗口分别跑：

```bash
docker logs --since 12h litellm 2>&1 \
  | grep -E "LLM Provider NOT provided|This model isn't mapped yet|No fallback model group found"
```

```bash
docker logs --since 12h gateway_semantic_router 2>&1 \
  | uv run python scripts/router_log_summary.py
```

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

```bash
docker logs --since 12h gateway_semantic_router 2>&1 > /tmp/intentmux-12h.ndjson
uv run python scripts/diagnose_router_state.py \
  --routes config/routes.yaml \
  --logs /tmp/intentmux-12h.ndjson
```

### 验收标准

- LiteLLM 同类 fallback/provider 错误增量为 0，或能定位到具体模型/链路；
- IntentMux 日志中 `route_id`、`target_model`、`reason`、`upstream_status` 都可读；
- 没有 `chat_completions/semantic-router` passthrough 400 复现；
- `pro-router` streaming `ReadTimeout` 没有复现，或复现时能关联具体 route/target/reason。

### 当前已完成窗口

本轮 timeout 字段修正后窗口已经跑过一次：

- LiteLLM provider/fallback 错误签名：0 命中
- IntentMux `route_complete`：6
- IntentMux `route_error`：0
- 可读字段已覆盖 `route_id`、`target_model`、`reason`、`upstream_status`

下一次应等真实生产流量继续积累后再跑 12h / 24h 窗口，不用为了凑样本主动制造生产请求。

## 问题三：IntentMux 执行层降耦设计

当前 IntentMux 做到了：

```text
request -> route_id -> target_model
```

但 `target_model` 仍可能是 LiteLLM router group，例如：

```text
strong -> pro-router
fast -> cheap-router
experimental -> free-probe-router
```

这意味着 IntentMux 能决定“意图分到哪一档”，但执行层 fallback 仍主要由 LiteLLM router
group 负责。一旦 LiteLLM 的 group/fallback/pre-call 组合出问题，IntentMux 只能记录，
不能修复执行。

### 目标方向

把 IntentMux 从“route 到 LiteLLM group”升级为“route 到候选执行模型列表”：

```text
request
  -> route_id
  -> policy_id
  -> candidate target list
  -> first viable LiteLLM executable model_name
  -> LiteLLM execution
```

### 设计原则

- IntentMux 负责第一道语义 fallback 和候选选择；
- LiteLLM 保留 provider 执行、鉴权、基础代理、监控；
- 不把 IntentMux 内部 route id 暴露给 LiteLLM `model` 参数；
- 默认仍保留 `semantic-router` 作为兼容入口；
- 不要求用户大改端点或客户端；
- 所有候选选择必须写入结构化日志。

### 初步配置形态

当前：

```yaml
routes:
  strong:
    target_model: pro-router
```

候选方向：

```yaml
routes:
  strong:
    targets:
      - model: opencode-go/deepseek-v4-pro
        reason: primary-coding
      - model: deepseek-ai/DeepSeek-V4-Pro
        reason: fallback-wide
      - model: cheap-router
        reason: final-budget-fallback
```

注意：这只是设计方向，不应在未验证前直接改生产配置。

### 验收标准

- 单 route 可配置多个候选 target；
- 日志能记录：
  - `route_id`
  - `selected_target_model`
  - `candidate_count`
  - `candidate_index`
  - `fallback_reason`
  - `upstream_status`
- 单个候选失败时，IntentMux 能尝试下一候选；
- 不记录 prompt 或 bearer token；
- LiteLLM 不再收到 IntentMux 的中间 route id；
- 现有 `target_model` 单值配置保持兼容。

## 推荐执行顺序

1. 已完成 LiteLLM timeout 配置整理。
2. 等真实流量积累后跑 12h / 24h 止血后日志观察。
3. 用观察结果决定是否需要先增强日志查询/审计工具。
4. 如果日志稳定，再写 IntentMux execution-candidates 设计文档。
5. 设计确认后再实现，不在救火状态下重构执行路径。

## 暂不做

- 不等待 LiteLLM 上游更新作为恢复生产的前置条件。
- 不立即重命名本地目录或 Docker service。
- 不重新打开 `enable_pre_call_checks`。
- 不把 `/v1/responses` 桥接交给 LiteLLM。
- 不在未设计前让 IntentMux 强行接管所有 provider routing。
