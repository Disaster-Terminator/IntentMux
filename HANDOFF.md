# IntentMux 巡检交接文档

> 更新时间：2026-05-12 UTC+8
> 当前状态：项目基本功能已进入生产试用；巡检编排交给本机 Hermes cron 体系，Codex 不负责 cron。
> 接力目标：Hermes 定时生成巡检报告；后续 Codex 只根据报告和真实日志改进 IntentMux 项目本体。

---

## 1. 责任边界

IntentMux 仓库负责：

- 提供可重复执行的日志 summary、budget gate、LiteLLM 入口 E2E 和预检脚本；
- 保持日志字段可审计、可关联、无 prompt/token/bearer 泄漏；
- 根据巡检报告暴露的问题改进路由策略、配置契约、日志口径和测试。

Hermes cron 体系负责：

- 定时调用本文件列出的巡检命令；
- 收集 stdout、退出码和关键摘要；
- 生成面向后续 Codex 回合阅读的报告。

Codex 后续不负责：

- 创建或维护 cron job；
- 决定本机报告投递渠道；
- 接管 Hermes 的调度、告警、重试或消息发送。

---

## 2. 生产路径与服务

仓库路径：

```bash
/path/to/gateway/gateway-semantic-router
```

持久审计日志路径：

```bash
/path/to/intentmux-runtime/logs/routes/YYYY-MM-DD.jsonl
```

当前生产入口：

- LiteLLM：`http://127.0.0.1:4000`
- IntentMux：`http://127.0.0.1:4001`
- LiteLLM 内的 `semantic-router` 模型组应指向 `http://intentmux:4001/v1`

容器名：

- `intentmux`
- `litellm`
- `litellm_db`
- `litellm_prometheus`

---

## 3. 推荐巡检命令

以下命令从仓库根目录执行。

### 3.1 Hermes cron 主入口

Hermes cron 只需要定时调用这个脚本：

```bash
cd /path/to/gateway/gateway-semantic-router
uv run python scripts/intentmux_daily_health.py
```

默认不会发真实 E2E 请求，只生成给 Codex 读取的巡检报告。产物写在持久日志目录旁边：

```text
/path/to/intentmux-runtime/logs/health/intentmux-health-YYYY-MM-DD.json
/path/to/intentmux-runtime/logs/health/intentmux-health-YYYY-MM-DD.md
/path/to/intentmux-runtime/logs/health/intentmux-health-latest.json
/path/to/intentmux-runtime/logs/health/intentmux-health-latest.md
```

报告包含：

- `ready`
- `route_summary_today`
- `route_summary_all_logs`
- `strict_budget`
- `tolerant_budget`
- `e2e`
- `paths`

其中 `route_summary_today` 是日常判断主口径，`route_summary_all_logs` 只作历史上下文。报告会保留 `slow_requests` top N 明细，方便 Codex 直接看尾延迟样本。

慢请求明细会自动带出阶段耗时字段，不需要 Hermes 额外解析或拼接：

- `decision_ms`：路由决策耗时，包含 hard rule / embedding 路径。
- `upstream_ms`：LiteLLM / 下游模型总耗时。
- `upstream_headers_ms`：流式请求拿到上游响应头的耗时。
- `upstream_body_ms`：流式请求响应体迭代耗时。

如果后续要让 Hermes 基于这些字段做阈值告警，再由 Codex 先写清楚阈值建议和报告字段变更，用户确认后再改 Hermes cron。

变更后或低频深巡检可手动加真实 E2E：

```bash
cd /path/to/gateway/gateway-semantic-router
uv run python scripts/intentmux_daily_health.py --run-e2e
```

### 3.2 分项命令：服务健康

```bash
curl -sS http://127.0.0.1:4001/ready
```

期望：

- `ready=true`
- `router.ok=true`
- `embedding.ok=true`
- `components.litellm.detail` 可以是 `status=401 auth_required`，这表示 LiteLLM 活着且需要鉴权。

### 3.3 分项命令：持久日志 summary

```bash
uv run python scripts/router_log_summary.py \
  /path/to/intentmux-runtime/logs/routes/*.jsonl \
  --slow-request-limit 10
```

报告应保留这些字段：

- `total/completed/errors`
- `routes`
- `targets`
- `reasons`
- `outcomes`
- `not_ok`
- `upstream_statuses`
- `upstream_non_200`
- `max_duration_ms`
- `duration_percentiles_ms`
- `slow_requests`

### 3.4 分项命令：当日严格 budget gate

```bash
uv run python scripts/check_route_error_budget.py \
  /path/to/intentmux-runtime/logs/routes/$(date +%F).jsonl \
  --min-total 1 \
  --max-error-rate 0 \
  --max-target-error-rate 0 \
  --max-route-error-rate 0 \
  --max-not-ok-rate 0 \
  --max-embedding-error-rate 0 \
  --max-upstream-status-rate 400=0
```

说明：

- 严格 budget 失败不等于服务一定不可用；
- 它的价值是把 `embedding_error`、上游 400、非 OK 请求显式暴露出来；
- Hermes 报告应记录退出码和 `reasons:` 行。

### 3.5 分项命令：当前生产观测容忍 budget

当严格 budget 失败时，可以再跑一条容忍阈值命令，用来区分“已知噪声”与“继续恶化”：

```bash
uv run python scripts/check_route_error_budget.py \
  /path/to/intentmux-runtime/logs/routes/$(date +%F).jsonl \
  --min-total 1 \
  --max-error-rate 0 \
  --max-target-error-rate 0 \
  --max-route-error-rate 0 \
  --max-not-ok-rate 0.02 \
  --max-embedding-error-rate 0.13 \
  --max-upstream-status-rate 400=0.02
```

这些阈值来自 2026-05-12 的真实观测基线：

- `embedding_error=12.64%`
- `not_ok=1.10%`
- `upstream_status 400=1.10%`

后续应根据连续报告收紧或调整，不要把这组数字当成永久 SLA。

### 3.6 分项命令：LiteLLM 入口严格 E2E

```bash
set -a
. /path/to/gateway/litellm/.env
set +a
uv run python scripts/e2e_litellm_entry.py \
  --litellm-base-url http://127.0.0.1:4000 \
  --log-container intentmux \
  --log-tail 300 \
  --require-request-id-log-match
```

期望：

- `strict_request_id_matches=3/3`
- `pro_nonstream` 和 `pro_stream` 命中 `route_id=strong`、`target_model=pro-router`
- `cheap_nonstream` 命中 `route_id=fast`、`target_model=cheap-router`
- `log_redaction` 通过

这条命令会发真实请求，适合作为低频巡检或变更后验收，不建议高频跑。

---

## 4. 报告格式建议

Hermes 报告建议至少包含：

```text
time: 2026-05-12T20:00:00+08:00
repo: /path/to/gateway/gateway-semantic-router
commit: <git rev-parse --short HEAD>

ready:
  exit_code: 0
  summary: ready=true router=true litellm=auth_required embedding=true

route_summary:
  log_files: routes/YYYY-MM-DD.jsonl
  total: ...
  routes: ...
  targets: ...
  reasons: ...
  outcomes: ...
  upstream_statuses: ...
  duration_percentiles_ms: ...
  slow_requests_top:
    - duration_ms=... request_id=... route=... target=... reason=... upstream_status=... decision_ms=... upstream_ms=...

strict_budget:
  exit_code: ...
  reasons: ...

tolerant_budget:
  exit_code: ...
  reasons: ...

e2e:
  skipped_or_exit_code: ...
  strict_request_id_matches: ...
  failures: ...
```

报告不要包含：

- prompt 原文；
- completion 原文；
- bearer token；
- LiteLLM master key；
- 完整请求体。

---

## 5. 后续 Codex 看报告时的判断口径

优先处理：

1. `/ready` 不通过。
2. LiteLLM 入口 E2E 失败，尤其是 request-id 无法关联到 IntentMux 日志。
3. `route_error > 0`。
4. `not_ok` 或 `upstream_status 400/5xx` 上升。
5. `embedding_error` 持续出现或比例升高。
6. `duration_percentiles_ms.p95/p99` 或 `slow_requests` 明显恶化。
7. `routes` 分布长期偏斜，尤其是 hard rule 导致上下文持续命中 strong，与两档路由产品语义冲突。

暂不直接改代码的情况：

- 单日样本量太小；
- 只有上游模型偶发 400，且 request-id 能关联、IntentMux 自身没有 `route_error`；
- 只有慢请求，但原因明显来自下游 provider 超时或模型排队。

需要沉淀为项目改进的问题：

- embedding 不可用时是否需要更强的降级/告警策略；
- hard rule 在长上下文 agent 框架下是否过度粘滞；
- `low_confidence` 占比长期过高时是否需要调 route bank 或阈值；
- 是否需要把 slow request 进一步拆成 IntentMux 耗时与 upstream 耗时；
- 是否需要为巡检报告生成专用 JSON 输出，减少 Hermes 解析文本的负担。

---

## 6. 最近已知基线

2026-05-12 巡检结果：

- `total=182`
- `errors=0`
- `routes: fast=146, strong=36`
- `targets: cheap-router=146, pro-router=36`
- `reasons: embedding_error=23, hard_rule:token=23, hard_rule:安全=13, low_confidence=123`
- `outcomes: success=180, upstream_non_200=2`
- `not_ok=2`
- `upstream_statuses: 200=180, 400=2`
- `max_duration_ms=117919.39`
- `p95=41123.26`
- 严格 LiteLLM-entry E2E：`strict_request_id_matches=3/3`

当时判断：

- IntentMux 本体服务正常；
- 两个 400 来自下游 LiteLLM/provider 语义，不是 IntentMux `route_error`；
- `embedding_error` 比例已经值得持续追踪；
- 延迟尾部明显，需要后续结合下游日志判断是否可由 IntentMux 改进。

---

## 7. 变更纪律

后续修改 IntentMux 后必须至少跑：

```bash
uv run pytest -q
uv run ruff check scripts/router_log_summary.py scripts/check_route_error_budget.py tests/test_router_log_summary.py tests/test_check_route_error_budget.py
curl -sS http://127.0.0.1:4001/ready
```

涉及运行时路由、配置、容器或 LiteLLM 接入的改动，还必须跑 LiteLLM 入口严格 E2E。

每次完成有效改动后提交并推送到 `origin/main`。
