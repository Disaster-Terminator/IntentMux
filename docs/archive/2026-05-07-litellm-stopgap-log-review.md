# 2026-05-07 LiteLLM 止血与日志复盘归档

## 范围

本归档覆盖 `d6d3fb9` 之后暴露的两类已处理前置问题：

- LiteLLM 配置没有正确读取 timeout；
- 止血后当前可读 Docker 日志窗口的健康度检查。

`d6d3fb9` 时间点：

```text
d6d3fb9caf8497ae5e8a6ebfc5bbf1ce35dcf5ac
2026-05-05 23:03:16 +0800
docs: rename project identity to IntentMux
```

## 任务一：timeout 配置读取

结论：已完成。

根因：

- LiteLLM v1.83.14 的 `Router.__init__()` 接收 `timeout` 与 `stream_timeout`；
- `router_settings.request_timeout` 不是有效 Router 参数；
- proxy 启动时只转发 `litellm.Router.get_valid_args()` 允许的 key；
- 因此旧配置会触发：

```text
Key 'request_timeout' is not a valid argument for Router.__init__(). Ignoring this key.
```

已执行变更：

- 备份：
  `/path/to/gateway/litellm/config.yaml.backup-20260507-timeout-field`
- 将 `/path/to/gateway/litellm/config.yaml` 中的
  `router_settings.request_timeout: 45` 改为 `router_settings.timeout: 45`
- 只重启 `litellm` 本体服务。

验证：

- `litellm` startedAt：`2026-05-07T06:36:28.740269488Z`
- `/health/readiness` 返回 200；
- 启动后日志中 `request_timeout` / `Router.__init__` warning 为 0；
- `/model/info` 返回 43 条，`db_model=false` 为 43 条，`db_model=true` 为 0；
- IntentMux preflight 通过；
- LiteLLM-entry E2E 通过；
- `pytest`：171 passed, 1 warning。

## 任务二：当前可读日志窗口复盘

结论：当前窗口可读，但日志持久性不足，不能覆盖完整两天。

容器日志窗口：

- `gateway_semantic_router` startedAt：`2026-05-07T06:20:35.962096818Z`
- `litellm` startedAt：`2026-05-07T06:36:28.740269488Z`

这意味着从 `d6d3fb9` 到当前的完整两天窗口不能仅靠当前 Docker stdout 复原。重启前暴露的问题只能依赖之前已经捕获的 HANDOFF、历史 grep 与人工记录。

当前可读 IntentMux 结构化日志统计：

```text
total=93 completed=93 errors=0 streams=85 nonstreams=8
routes: experimental=2, fast=44, strong=47
targets: cheap-router=44, free-probe-router=2, pro-router=47
reasons: embedding=4, hard_rule:PR=6, hard_rule:debug=7, hard_rule:异常=11, hard_rule:报错=15, hard_rule:线上=8, low_confidence=42
error_types: none
upstream_statuses: 200=92, 400=1
upstream_non_200: status=400 target=cheap-router reason=low_confidence stream=true=1
max_duration_ms=63893.91
```

延迟分布：

```text
count=93 min=872.78 p50=6070.22 p90=24305.3 p95=30327.22 max=63893.91
```

route budget：

```text
FAIL route_error_budget
reason: upstream_status 400 rate 0.0108 exceeds max_upstream_status_rate 0.0000
```

LiteLLM 当前可读窗口错误签名：

```text
request_timeout=2
Router.__init__=2
LLM Provider NOT provided=0
This model isn't mapped yet=0
No fallback model group found=0
No api key passed in=15
ReadTimeout=0
RemoteProtocolError=0
```

其中 `request_timeout` / `Router.__init__` 来自修正前重启；修正后的窗口为 0。
`No api key passed in` 来自未带 key 的探测或 UI/health 访问，不是 IntentMux 业务链路失败。

## 暴露的问题

### 1. 日志没有项目级持久化

IntentMux 目前依赖容器 stdout。容器重启后，只能分析当前生命周期内的日志。对“从某个 commit 起两天内发生了什么”这种问题，项目没有自己的审计数据边界。

影响：

- 无法可靠复盘跨重启窗口；
- 无法稳定支撑 12h / 24h 产品改进分析；
- 生产 E2E 只能做当下验证，不能形成长期审计基线。

### 2. `route_complete` 不等于业务成功

当前有一条：

```text
route_id=fast target_model=cheap-router reason=low_confidence stream=true upstream_status=400
```

事件仍是 `route_complete`，因此只看 `route_error` 会误判健康。预算脚本能捕获 `upstream_status=400`，但产品日志语义还不够直接。

### 3. `low_confidence` 占比高

当前窗口 `low_confidence=42/93`，主要落到 `fast -> cheap-router`。

这可能是正常的保守策略，也可能说明 route bank / 阈值 / embedding 匹配还需要用历史数据校准。没有持久日志之前，不应直接改阈值。

### 4. 执行层仍依赖 LiteLLM group

IntentMux 当前能做：

```text
request -> route_id -> target_model
```

但 `target_model` 仍是 `pro-router` / `cheap-router` / `free-probe-router` 这类 LiteLLM group。LiteLLM group/fallback 出问题时，IntentMux 只能观察，不能主动选择下一候选执行模型。

## 归档结论

任务一完成；任务二在当前可读窗口完成，但同时证明日志持久化能力不足。下一步不应先做大规模执行层重构，而应先补齐项目级审计日志与日志分析口径，再设计 IntentMux 自主候选执行层。
