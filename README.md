# IntentMux

> OpenAI-compatible `lite` / `deep` 意图路由网关。
> 默认成本优先，只有证据足够时升级到更强模型。

<p align="center">
  <img alt="runtime Python 3.11+" src="https://img.shields.io/badge/runtime-Python%203.11%2B-3776AB">
  <img alt="entries intentmux lite deep" src="https://img.shields.io/badge/entries-intentmux%20%7C%20lite%20%7C%20deep-0EA5E9">
  <img alt="LiteLLM sidecar compatible" src="https://img.shields.io/badge/LiteLLM-sidecar%20compatible-16A34A">
  <img alt="route logs metadata only" src="https://img.shields.io/badge/route%20logs-metadata%20only-7C3AED">
</p>
<p align="center">
  <img alt="built with FastAPI" src="https://img.shields.io/badge/built%20with-FastAPI-009688">
  <img alt="kernel Aurelio Semantic Router" src="https://img.shields.io/badge/kernel-Aurelio%20Semantic%20Router-F59E0B">
  <img alt="config YAML" src="https://img.shields.io/badge/config-YAML-CB171E">
  <img alt="tests pytest" src="https://img.shields.io/badge/tests-pytest-0A9EDC">
  <img alt="package uv" src="https://img.shields.io/badge/package-uv-DE5FE9">
  <img alt="license Apache-2.0" src="https://img.shields.io/badge/license-Apache--2.0-111827">
</p>

[English](README.en.md)

<table>
  <tr>
    <td><strong>双档路由</strong><br>`intentmux` 自动分流；`lite` / `deep` 可作为显式模型入口。</td>
    <td><strong>边界清晰</strong><br>LiteLLM 继续负责 provider routing、fallback、限流、key 和 budget。</td>
  </tr>
  <tr>
    <td><strong>可审计日志</strong><br>route audit 默认只记录元数据；私有部署可显式开启 prompt review log。</td>
    <td><strong>验证优先</strong><br>用 `/ready`、preflight、E2E、daily health 和 Beads 校验当前状态。</td>
  </tr>
</table>

## 项目定位

IntentMux 是一个轻量路由 sidecar。它接收 OpenAI-compatible chat
completion 请求，把 `model=intentmux` 的请求路由到两个产品级 route：

- `lite`：低风险、低成本、普通问答和轻量任务。
- `deep`：代码、debug、架构、高风险判断和需要更强模型的任务。

IntentMux 不提供模型，也不替代 LiteLLM、OpenRouter 或其他 provider gateway。
它只负责入口模型语义、路由决策、协议代理和可审计日志。

```text
model=intentmux -> route_id(lite/deep) -> target_model -> OpenAI-compatible upstream
```

两种部署形态都支持：

```text
Direct gateway:
client -> IntentMux :4001/v1, model=intentmux|lite|deep
       -> OpenAI-compatible upstream

LiteLLM-first sidecar:
client -> LiteLLM :4000, model=intentmux
       -> IntentMux :4001
       -> LiteLLM target model group
```

如果已有 LiteLLM，推荐继续让 LiteLLM 管 provider routing、fallback、key、
budget 和模型池。IntentMux 只做意图路由。

## 路由原则

默认决策顺序：

```text
explicit route -> hard escalation -> semantic score + threshold -> fallback lite
```

- `model=lite` / `model=deep` 或 `metadata.route_id` 是显式路由。
- hard rules 只用于安全、凭据泄露、生产事故、数据损坏等高风险强制升级。
- 普通工程词、工具调用结构、长上下文和 agent 形态只进入审计信号，不直接升级。
- embedding 不可用时按 `fallback_route_id` fail open，默认是 `lite`。
- upstream 连接错误或 5xx 返回脱敏 `502`；upstream 4xx 按代理语义透传，同时记入审计日志。

默认在线路由内核是 [Aurelio Semantic Router](https://docs.aurelio.ai/semantic-router/get-started/introduction)。
内置 `basic` 只作为 fallback/debug baseline。

## 核心依赖与致谢

IntentMux 默认依赖 Aurelio Semantic Router 作为成熟路由匹配内核，当前默认形态是
`HybridRouter + HybridLocalIndex`。
IntentMux 在其上提供 OpenAI-compatible 网关入口、`lite` / `deep` 产品语义、
运行时配置、日志审计、质量报告和 LiteLLM sidecar 集成。

## 快速开始

本地进程：

```bash
uv run python -m router.app
```

容器示例：

```bash
uv run python scripts/init_runtime_home.py
docker compose -f examples/docker-compose.yml up -d --build
```

默认端点：

| 服务 | 地址 |
| --- | --- |
| IntentMux | `http://127.0.0.1:4001` |
| LiteLLM upstream | `http://127.0.0.1:4000` |
| Embedding upstream | `http://127.0.0.1:1234/v1/embeddings` |

首次接入先做四件事：

1. 选择直连 IntentMux，或在 LiteLLM 中新增 `intentmux` 模型入口。
2. 复制 `examples/intentmux-home/` 到自己的运行时目录。
3. 在运行时 `config/routes.yaml` 中配置 `routes.lite.target_model` 和
   `routes.deep.target_model`。
4. 跑 `/ready` 和 preflight，再用 decision endpoint 查看一次真实路由结果。

## 配置合同

核心配置文件是 `routes.yaml`：

```yaml
route_model: intentmux
fallback_route_id: lite

routes:
  lite:
    target_model: your-lite-model
    description: 低风险、普通问答、解释、翻译、轻量总结
    utterances:
      - 帮我解释一下这段概念

  deep:
    target_model: your-deep-model
    description: 代码、debug、架构、高风险判断
    utterances:
      - 这个线上 bug 为什么偶发
```

生产部署应显式设置：

- `INTENTMUX_HOME`：运行时目录，保存真实配置、语义资产、日志和缓存。
- `ROUTER_CONFIG`：运行时 `routes.yaml` 路径。
- `ROUTER_CLOUD_MODE=true`：云端/公网部署启用 fail-closed 安全检查。
- `ROUTER_INBOUND_API_KEY`：云端/公网部署必须配置入口认证。
- `ROUTER_LITELLM_BASE_URL`：上游 OpenAI-compatible gateway。
- `ROUTER_EMBEDDING_URL` / `ROUTER_EMBEDDING_MODEL`：embedding upstream。
- `ROUTER_AUDIT_LOG_ENABLED=true` 和 `ROUTER_AUDIT_LOG_DIR`：持久 route audit。
- `ROUTER_REQUIRE_ROUTE_BANK=true`：生产 route bank 缺失时启动失败。

`/ready` 会暴露当前配置来源、运行时目录、日志状态、route bank 是否加载和每个 route
的 utterance 数量。不要盲信文档或旧状态文件，先看 live `/ready` 和最新日志。
云端运行时资产边界见 [docs/cloud_hosting.md](docs/cloud_hosting.md)。

## API

IntentMux 当前支持：

- `GET /health`
- `GET /ready`
- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/intentmux/decision`

入口模型：

| Model | 用途 |
| --- | --- |
| `intentmux` | 默认自动路由 |
| `lite` | 显式走 `lite` route |
| `deep` | 显式走 `deep` route |

`/v1/models` 只广告 `intentmux`、`lite`、`deep`，不泄漏部署侧 `target_model`。

查看一次路由决策，不转发到上游：

```bash
curl http://127.0.0.1:4001/v1/intentmux/decision \
  -H "Content-Type: application/json" \
  -d '{"model":"intentmux","messages":[{"role":"user","content":"这个线上 bug 为什么偶发？"}]}'
```

decision response 会返回 `route_id`、`target_model`、`policy_id`、分数、阈值、
margin 和 route-bank match provenance。匹配样本文本不会出现在响应或 audit log 中。

## 验证优先

这个项目默认进入日志驱动维护。文档只能说明当前意图，真正接手时应先验证 live 状态。

常用检查：

```bash
uv run pytest -n auto -q
uv run ruff check .
uv run python scripts/verify_route_contract.py
uv run python scripts/preflight.py --router-base-url http://127.0.0.1:4001
curl -fsS http://127.0.0.1:4001/ready
```

生产或私有部署还应跑 daily health：

```bash
uv run python scripts/intentmux_daily_health.py \
  --log-dir /path/to/intentmux-home/logs \
  --timezone Asia/Shanghai \
  --min-route-records 1 \
  --run-e2e
```

代码或镜像变更需要 rebuild/recreate IntentMux sidecar；配置、route bank 或环境变量变更
需要 restart。更完整的门禁见 [docs/production_rollout_gate.md](docs/production_rollout_gate.md)。

## 日志和质量闭环

默认 route audit 只记录元数据：route、target、reason、状态码、耗时、request id、
决策分数和 match provenance。不记录 prompt、completion、token usage 或 bearer token。

可选 prompt review log 只适合私有部署，用于本地复核和生成脱敏样本。公开环境应保持关闭。

质量改进的基本原则：

1. 从 route audit 中找 low confidence、upstream failure、slow request 和分布漂移。
2. 用 bounded replay / eval / quality report 做 before/after 对比。
3. 只有接受、脱敏、可复核的样本才能进入 eval 或 route bank。
4. route bank、threshold、margin、hard rule 变化必须附带报告，不靠口头判断上线。

相关文档：

- [docs/PROJECT_CONTROL.md](docs/PROJECT_CONTROL.md)：当前产品控制面和工作顺序。
- [docs/PATROL_HANDOFF.md](docs/PATROL_HANDOFF.md)：巡检和运行时交接。
- [docs/log_driven_quality_loop.md](docs/log_driven_quality_loop.md)：日志驱动质量闭环。
- [docs/router_data_pipeline_research.md](docs/router_data_pipeline_research.md)：语义资产管线。
- [docs/cloud_hosting.md](docs/cloud_hosting.md)：云端托管与运行产物边界。
- [docs/production_rollout_gate.md](docs/production_rollout_gate.md)：生产变更门禁。

## 当前状态

IntentMux 已具备可运行的两档路由、LiteLLM sidecar 兼容、metadata-only audit、
route-bank provenance、preflight、E2E、daily health 和质量报告脚本。

默认不再主动调整路由行为。后续改动应由日志、replay、eval 或 calibration report
证明有重复模式后再推进。

后续可能继续打磨的方向：

- accepted findings 到 redacted regression cases 的导入门禁；
- 更有代表性的公开 eval / calibration 证据；
- 日志驱动的 route bank、threshold、margin 或 hard rule 小步调整。
