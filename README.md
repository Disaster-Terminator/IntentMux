# IntentMux

> 轻量 OpenAI 兼容路由网关，把请求按复杂度路由到 `lite` / `deep` 两档模型。<br>
> 可独立运行，也一等支持 LiteLLM-first sidecar 部署。

<p align="center">
  <img alt="runtime Python 3.11+" src="https://img.shields.io/badge/runtime-Python%203.11%2B-3776AB">
  <img alt="entries auto lite deep" src="https://img.shields.io/badge/entries-auto%20%7C%20lite%20%7C%20deep-0EA5E9">
  <img alt="LiteLLM sidecar compatible" src="https://img.shields.io/badge/LiteLLM-sidecar%20compatible-16A34A">
  <img alt="route logs metadata only" src="https://img.shields.io/badge/route%20logs-metadata%20only-7C3AED">
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

IntentMux 是一个轻量 OpenAI 兼容路由网关，把请求按复杂度路由到 `lite` / `deep` 两档模型。它可以独立作为 `base_url`，也可以作为 LiteLLM-first sidecar 接入现有 LiteLLM 主入口。

<table>
  <tr>
    <td><strong>双档路由</strong><br>`auto` 自动分流；`lite` / `deep` 可作为显式模型入口。</td>
    <td><strong>边界清晰</strong><br>LiteLLM 继续负责 provider routing、fallback、限流、key 和 budget。</td>
  </tr>
  <tr>
    <td><strong>可审计日志</strong><br>route audit 默认只记录元数据；本地私有部署可显式开启 prompt review log。</td>
    <td><strong>生产前验证</strong><br>提供 preflight、LiteLLM-entry E2E、日志 summary 和 route-error budget gate。</td>
  </tr>
</table>

## 项目边界

IntentMux 不是模型提供商，也不需要 LiteLLM 才能启动。它负责 OpenAI-compatible 网关协议、入口模型语义、路由决策和审计日志；上游可以是 LiteLLM，也可以是任意 OpenAI-compatible 服务。生产环境如果已经有 LiteLLM，推荐继续让 LiteLLM 负责 provider routing、provider fallback、provider credentials、virtual keys、budgets 和 model pools。

当前产品控制面见 [docs/PROJECT_CONTROL.md](docs/PROJECT_CONTROL.md)。它定义了
IntentMux 的可学习路由愿景、数据集边界、当前实现差距和活跃工作顺序；旧计划文档只在
该控制面允许时作为背景材料使用。

```text
model=auto -> route_id(lite/deep) -> target_model -> OpenAI-compatible upstream
```

两种部署形态都是一等支持：

```text
Direct gateway:
client -> IntentMux :4001/v1, model=auto|lite|deep
       -> OpenAI-compatible upstream

LiteLLM-first sidecar:
client -> LiteLLM :4000, model=semantic-router
       -> IntentMux :4001
       -> LiteLLM :4000 target model group
```

规范入口模型：

- `auto`：默认自动路由入口。
- `lite`：显式轻量、低成本、低风险 tier。
- `deep`：显式深度推理、高能力、高置信 tier。

| Requested model | 含义 | 行为 |
| --- | --- | --- |
| `auto` | 推荐自动路由入口 | 执行 IntentMux 路由 |
| `semantic-router` | LiteLLM sidecar 入口名 | 与 `auto` 等价，适合 LiteLLM-first 拓扑 |
| `lite` | 显式轻量 tier | 路由到配置的 `lite.target_model` |
| `deep` | 显式高能力 tier | 路由到配置的 `deep.target_model` |

入口边界：

- `semantic-router`：LiteLLM sidecar 入口名，继续接受；它是 LiteLLM-first 拓扑里的语义路由入口。
- `auto`：IntentMux direct gateway 的规范自动路由入口。
- `lite` / `deep`：IntentMux 的产品 route id 和显式入口。

`/v1/models` 只广告规范入口 `auto`、`lite`、`deep`，不广告 `semantic-router`，也不泄漏本地 LiteLLM model group 名称。`target_model` 是部署侧配置值，不是产品接口。

部署时可以让 IntentMux 独立作为 gateway，也可以把它作为 LiteLLM 旁路 sidecar 独立管理；不要把 LiteLLM 挂载目录、token、`.env` 或 provider 凭据加入本仓库。

当前兼容范围：

- 支持 `/health`、`/ready`、`/v1/models`、`/v1/chat/completions` 和 `/v1/semantic-router/decision`。
- 支持 streaming / non-streaming chat completion pass-through。
- 不声明完整 OpenAI API 兼容，不实现 `/v1/responses`。
- 不管理 provider pools；provider routing、key、budget、fallback 请交给 LiteLLM 或其他 OpenAI-compatible upstream。
- IntentMux 入站鉴权、上游鉴权和 embedding 鉴权是三组独立 secret。
- embedding 降级按路由 fallback 处理；上游传输或状态失败返回受控、脱敏的 gateway error。

## 适合什么场景

- 你已经有 LiteLLM / OpenAI-compatible gateway。
- 你想用很小的接入成本，把一部分请求按意图分到不同模型组。
- 你希望路由决策可回放、可审计、可用日志继续改进。
- 你不想引入一个大型调度平台，也不想让客户端大改端点。

IntentMux 的差异化不是“再造一个复杂 router”，而是轻量、本地、协议兼容、快速部署、日志可读。成熟的 provider 路由、fallback、限流、鉴权、key 和 budget 仍交给 LiteLLM。

默认路由方法借鉴 strong/weak 两档 LLM router 和 Semantic Router 的成熟做法：

```text
explicit override -> high-precision hard escalation -> semantic score + threshold -> fallback lite
```

路由内核是可插拔的：

- `basic`：内置轻量 baseline，使用本地 embedding、route bank、threshold/margin 和
  持久化向量缓存。
- `aurelio`：可选的 Aurelio Semantic Router adapter，在请求路径内调用 Python
  library 评分；IntentMux 仍负责 OpenAI-compatible API、LiteLLM sidecar 转发、
  hard rule、fallback、日志和审计字段。

启用 Aurelio 内核需要安装可选依赖组并显式设置环境变量：

```bash
uv sync --group upstream-router
ROUTER_ROUTE_KERNEL=aurelio uv run python -m router.app
```

不要整仓搬运或复制上游核心代码；成熟 router 应以 dependency adapter 的方式接入。
RouteLLM 当前作为评估和阈值校准方法来源，不进入在线请求路径。

`hard_rules` 只用于安全、密钥泄露、线上事故、数据损坏等高风险强制升级场景。
`PR`、`debug`、`部署`、`索引`、`异常`、`报错` 等容易被 agent 累积上下文污染的普通工程词，
默认交给语义样本、相似度分数和阈值判断，避免后续轻量请求长期粘在 `deep`。

OpenAI-compatible 请求如果带有 `tools` / legacy `functions`、工具调用历史、
`tool_choice`，或达到长上下文多轮阈值，IntentMux 只把这些结构信息写入
`format_signals` 供日志审计和候选复核使用。请求结构本身不会直接升级到
`deep`；是否升级仍由显式 route、高精度 hard rule、语义样本和阈值共同决定。

## 快速运行

```bash
uv run python -m router.app
```

首次接入先确认这四件事：

1. 选择运行形态：直连 IntentMux `:4001`，或在 LiteLLM 里新增 `semantic-router` sidecar 入口。
2. 准备运行时配置：复制 `examples/intentmux-home/` 到自己的持久化目录，生产用 `ROUTER_CONFIG=/data/config/routes.yaml` 指向它。
3. 修改模型映射：只在运行时 `routes.yaml` 里改 `routes.lite.target_model` 和 `routes.deep.target_model`，不要把本机 LiteLLM 路径或 token 写进仓库。
4. 验证启动状态：跑 `/ready`、`scripts/preflight.py`，再用 `/v1/semantic-router/decision` 看一条请求的 `route_id`、`target_model` 和 `match_source`。

默认端点：

| 服务 | 地址 |
| --- | --- |
| IntentMux sidecar | `http://127.0.0.1:4001` |
| LiteLLM upstream | `http://127.0.0.1:4000` |
| Embedding upstream | `http://127.0.0.1:1234/v1/embeddings` |

常用环境变量：

- `INTENTMUX_HOME`
- `ROUTER_CONFIG`
- `ROUTER_HOST`
- `ROUTER_PORT`
- `ROUTER_LITELLM_BASE_URL`
- `ROUTER_LITELLM_API_KEY`
- `ROUTER_INBOUND_API_KEY`
- `ROUTER_LITELLM_TIMEOUT`
- `ROUTER_EMBEDDING_URL`
- `ROUTER_EMBEDDING_MODEL`
- `ROUTER_ROUTE_KERNEL`：`basic` 或 `aurelio`。默认 `basic`；`aurelio` 需要
  `uv sync --group upstream-router` 或等价安装。
- `ROUTER_ACCESS_LOG`
- `ROUTER_AUDIT_LOG_ENABLED`
- `ROUTER_AUDIT_LOG_DIR`
- `ROUTER_PROMPT_LOG_MODE`
- `ROUTER_PROMPT_LOG_DIR`
- `ROUTER_READINESS_TIMEOUT`

IntentMux 支持本地进程和容器两种运行方式。先区分三类目录：

| 路径 | 作用 | 是否应直接改 |
| --- | --- | --- |
| `config/routes.yaml` | 仓库内置开发/示例配置；未设置 `ROUTER_CONFIG` 时读取 | 可以用于本地开发，不是生产状态 |
| `examples/intentmux-home/` | 可复制的运行时目录模板 | 不作为生产目录直接挂载 |
| `.intentmux-home/` | 默认本地运行时目录，已被 git ignore | 本地试用和 dogfood 可改这里 |
| `$INTENTMUX_HOME` / 容器内 `/data` | 显式运行时目录，保存真实配置、语义资产和日志 | 生产应改这里 |

配置读取规则：

```text
本地进程: ROUTER_CONFIG 已设置 -> 指向的 routes.yaml
本地进程: ROUTER_CONFIG 未设置且 INTENTMUX_HOME 已设置 -> $INTENTMUX_HOME/config/routes.yaml
本地进程: ROUTER_CONFIG 未设置且 .intentmux-home/config/routes.yaml 存在 -> 读取它
本地进程: 上述运行时配置都不存在 -> config/routes.yaml
compose 示例: ROUTER_CONFIG=/data/config/routes.yaml
```

日志路径读取规则：

```text
ROUTER_AUDIT_LOG_DIR 已设置 -> 指向的 route audit log 目录
ROUTER_AUDIT_LOG_DIR 未设置 -> $INTENTMUX_HOME/logs/routes 或 .intentmux-home/logs/routes
ROUTER_PROMPT_LOG_DIR 已设置 -> 指向的 prompt review log 目录
ROUTER_PROMPT_LOG_DIR 未设置 -> $INTENTMUX_HOME/logs/prompts 或 .intentmux-home/logs/prompts
```

容器不是唯一部署形态；挂载目录也不是开发必需项，而是生产持久化配置、语义资产和
audit JSONL 的推荐方式。

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
    logs/prompts/YYYY-MM-DD.jsonl   # optional local-only prompt review log
```

容器内约定：

```text
/app   # 镜像代码和内置样例
/data  # 用户挂载的 IntentMux home
```

compose 示例：

仓库提供通用 compose 示例：[examples/docker-compose.yml](examples/docker-compose.yml)。

```bash
uv run python scripts/init_runtime_home.py
docker compose -f examples/docker-compose.yml up -d --build
```

默认示例会把仓库根目录下的 `.intentmux-home/` 挂载到容器 `/data`，它已被 `.gitignore` 排除，适合本地试用和 dogfood。`scripts/init_runtime_home.py` 会从 [examples/intentmux-home](examples/intentmux-home) 幂等初始化这个目录：补齐缺失文件和运行时子目录，不覆盖已有配置。生产部署可以复制同一个模板到源码仓库外的持久化位置，再显式用 `INTENTMUX_HOME=/path/to/intentmux-home` 指向它。

可覆盖变量：

- `INTENTMUX_PORT`：宿主机暴露端口，默认 `4001`，示例 compose 默认只绑定 `127.0.0.1`。
- `INTENTMUX_HOME`：宿主机上的 IntentMux home，默认 `../.intentmux-home`（相对 `examples/docker-compose.yml`）。
- `ROUTER_LITELLM_BASE_URL`：LiteLLM 上游地址，默认 `http://host.docker.internal:4000`。
- `ROUTER_LITELLM_API_KEY`：IntentMux 调用上游 LiteLLM 使用的专用 key。设置后，IntentMux 不会把入站 `Authorization` 原样转发给上游。
- `ROUTER_INBOUND_API_KEY`：可选的 IntentMux 入站 key，用于保护直连 sidecar 的 `/v1/chat/completions` 和 `/v1/semantic-router/decision`；不影响 `/health` 和 `/ready`。
- `ROUTER_AUDIT_LOG_TIMEZONE`：审计日志按天分区的时区，默认 `Asia/Shanghai`。
- `ROUTER_PROMPT_LOG_MODE`：可选 prompt review log，默认 `off`。可设为 `redacted` 或 `raw_local`，只适合本地私有审查。
- `ROUTER_PROMPT_LOG_DIR`：prompt review log 目录，示例 compose 固定为 `/data/logs/prompts`。
- `ROUTER_PROMPT_LOG_MAX_CHARS`：每条 latest user text 最多记录字符数，默认 `20000`。
- `ROUTER_EMBEDDING_URL`：embedding 上游地址，默认 `http://host.docker.internal:1234/v1/embeddings`。
- `ROUTER_EMBEDDING_MODEL`：embedding 模型名。
- `ROUTER_EMBEDDING_API_KEY`：可选的 embedding 上游 key，设置后按 OpenAI-compatible `Authorization: Bearer ...` 发送。
- `ROUTER_EMBEDDING_HEADERS_JSON`：可选的 embedding 自定义 headers JSON，例如 `{"X-Provider":"local"}`。只允许字符串键值。
- `ROUTER_ROUTE_EMBEDDING_CACHE_ENABLED`：是否启用静态 route bank 向量落盘缓存，默认 `true`。
- `ROUTER_ROUTE_EMBEDDING_CACHE_PATH`：route bank 向量缓存文件。未设置时默认 `$INTENTMUX_HOME/cache/route-embeddings.json`，没有 `INTENTMUX_HOME` 时使用 `.intentmux-home/cache/route-embeddings.json`。
- `ROUTER_REQUIRE_ROUTE_BANK`：可选严格门禁。示例 compose 默认 `true`；设为 `true` 后，`route_bank_path` 缺失、文件不存在、或没有为已声明 route 提供任何有效 utterance 时启动失败。

LiteLLM 入口模型示例见 [examples/litellm-model-entry.yaml](examples/litellm-model-entry.yaml)。如果 IntentMux 和 LiteLLM 在同一个 compose network 中，`api_base` 可以使用 `http://intentmux:4001/v1`；如果 LiteLLM 在宿主机或另一个网络里，请改成它能访问到的 IntentMux 地址。

鉴权边界：

- LiteLLM 模型入口里的 `api_key` 用于 `LiteLLM -> IntentMux`。
- `ROUTER_INBOUND_API_KEY` 用于保护 `IntentMux` 的入站请求，适合直连 sidecar 或不完全信任的内部网络。
- `ROUTER_LITELLM_API_KEY` 用于 `IntentMux -> LiteLLM`，不要依赖入站 `Authorization` 透传给上游。
- `ROUTER_EMBEDDING_API_KEY` 和 `ROUTER_EMBEDDING_HEADERS_JSON` 只用于 `IntentMux -> embedding upstream`。`/ready` 探测和实际 embedding 请求使用同一套 headers。

更新同步规则：

- 只改 `/data/config/routes.yaml`、`/data/semantic_sets/route_bank.yaml` 或环境变量：重启 IntentMux sidecar，让启动时加载的配置和向量索引刷新。route bank 向量缓存会按 route utterance 来源、顺序、文本 hash 和 embedding model 自动失效。
- 改 Python 代码、`Dockerfile`、内置 `config/` 或 `examples/`：重新构建镜像，再重建 IntentMux sidecar。
- 只改 README、测试或离线脚本：不影响正在运行的容器，但仍应跑对应测试或校验脚本。

compose 部署的常用更新命令：

```bash
docker compose -f examples/docker-compose.yml build intentmux
docker compose -f examples/docker-compose.yml up -d intentmux
```

仓库也提供一个人工触发的 Compose sidecar rollout helper：

```bash
INTENTMUX_COMPOSE_FILE=examples/docker-compose.yml \
  scripts/rollout_compose_intentmux.sh --yes
```

这个脚本会按顺序执行测试、route contract 校验、重建前 `/ready`、legacy sidecar
preflight、只重建/重启 `intentmux` service、重建后 `/ready` 和容器 health、
canonical preflight 复验，以及 cost-first 决策冒烟。
它是通用 Compose helper，不是本仓库内置的生产拓扑；真实重启必须显式传
`--yes`，`--dry-run` 可用于先审计将要执行的命令。

生产路径不应写进仓库脚本或 README；把 `INTENTMUX_COMPOSE_FILE`、
`INTENTMUX_BASE_URL`、`INTENTMUX_RUNTIME_CONFIG` 等变量放到本机未跟踪
wrapper 或 shell 环境中。RayStorm 本机生产 wrapper 属于本机运维资产，
不应进入 public repo。
如需同步挂载目录里的 `routes.yaml`，必须显式加 `--sync-runtime-config`；
默认只部署代码镜像，不覆盖用户 runtime config。

IntentMux 暂未实现热重载，生产变更按“配置重启、代码重建”的规则处理。

仓库里的 `examples/intentmux-home/` 是可复制的运行时目录模板。`/data` 不应放 LiteLLM 的 `.env`、provider token 或数据库。只有在明确启用 `ROUTER_PROMPT_LOG_MODE=raw_local` 时，`/data/logs/prompts` 才会保存 prompt review log；这个目录只适合本地私有审查，不应提交、上传或贴到 issue。

运行时目录是用户部署资产，不是本仓库的源码内容。本仓库默认通过 `.gitignore` 排除
`*-runtime/`、本地 source samples 和 `data/semantic_sets/*.yaml`，避免把用户语义资产、
审计日志或生产配置误提交。仓库只跟踪可运行 example：
[examples/route_bank.sample.yaml](examples/route_bank.sample.yaml) 和
[examples/eval_bank.sample.yaml](examples/eval_bank.sample.yaml)。
生产部署应把运行时目录单独备份和迁移。

其中 `config/routes.yaml` 定义产品级 `route_id` 到 LiteLLM `target_model` 的映射，
`semantic_sets/route_bank.yaml` 必须使用同一组规范 `route_id` 作为 key，例如
`lite`、`deep`，不能使用 `your-lite-model`、`your-deep-model`
这类部署侧 target model 名称作为 key。

仓库提供可跟踪的精简 route bank example：[examples/route_bank.sample.yaml](examples/route_bank.sample.yaml)。
它用于展示 source/license 元数据、route bank 形状，以及 `utterance.source` 如何支撑
`match_source` 审计；真实部署应离线生成或维护自己的
`/data/semantic_sets/route_bank.yaml`。
`scripts/build_route_bank.py` 生成的 route bank 会写入 `generated` 元数据，包括生成工具、
git commit、生成时间、source manifest hash 和每个 source 的原始行数，便于后续追溯资产来源。

生产环境如果把 route bank 视为路由质量资产，应在 `routes.yaml` 中设置
`require_route_bank: true`，或通过 `ROUTER_REQUIRE_ROUTE_BANK=true` 开启。
这样可以避免 route bank 路径写错时服务静默回退到 seed utterances，导致灰度验证误判。
`/ready` 的 `components.router.detail` 会暴露 `route_bank_loaded` 和每个 route 的
utterance 数量，用来快速确认运行时实际加载的路由资产规模。

IntentMux 默认把静态 route bank 的 embedding 向量缓存到运行时目录的
`cache/route-embeddings.json`。缓存只覆盖 route bank utterances；每条真实请求仍会实时
embedding 一次，然后和缓存中的 route vectors 比分。缓存 manifest 包含 embedding model
和 route bank 指纹，route utterance 文本、来源或顺序变更后会自动重建。读取或写入缓存失败
不会让在线请求失败，只会退回到重新嵌入 route bank。

## 入口模型

新默认接入方式是把 IntentMux 作为 OpenAI-compatible `base_url`，客户端请求规范入口模型：

```text
client -> IntentMux :4001/v1, model=auto|lite|deep
       -> route_id(lite/deep)
       -> target_model
       -> OpenAI-compatible upstream
```

- `model=auto`：执行正常路由。
- `model=lite` / `model=deep`：显式指定 route id，跳过语义判断。
- `/v1/models`：只返回 `auto`、`lite`、`deep`。

LiteLLM sidecar 方式仍然支持：客户端继续请求 LiteLLM `:4000`，把模型名切到入口 `semantic-router`。

```text
client -> LiteLLM :4000, model=semantic-router
       -> IntentMux :4001
       -> route_id
       -> target_model
       -> LiteLLM model group
```

在 LiteLLM 中把 `semantic-router` 配置为指向 IntentMux sidecar 的模型入口后，客户端即可通过这个模型名触发自动路由。`semantic-router` 是 LiteLLM sidecar 入口，不会出现在 IntentMux `/v1/models` 的 direct gateway 推荐列表中。

## 配置模型

`config/routes.yaml` 的核心结构：

```yaml
route_model: auto
fallback_route_id: lite

routes:
  lite:
    target_model: your-lite-model
    description: 低风险、普通问答、解释、翻译、格式转换、轻量总结
    utterances:
      - 帮我解释一下这段概念

  deep:
    target_model: your-deep-model
    description: 代码、debug、架构、agent、多步推理、高风险判断
    utterances:
      - 这个线上 bug 为什么偶发
```

`target_model` 是 IntentMux 转发给上游 OpenAI-compatible gateway 的真实模型名。
在 LiteLLM-first 部署里，它通常就是 LiteLLM 的模型组名。`lite` / `deep`
到 `target_model` 的映射属于路由策略，统一写在运行时 `routes.yaml`，不再拆到环境变量里。

运行时校验会阻止递归配置：入口模型本身不能作为 route id 或 target model，`fallback_route_id` 必须存在。现有 LiteLLM sidecar 部署可以继续接受 `semantic-router` 作为 `auto` 的兼容入口。

生产容器中应通过 `ROUTER_CONFIG=/data/config/routes.yaml` 指向挂载配置。本地开发未设置 `ROUTER_CONFIG` 时，默认读取仓库内 `config/routes.yaml`。

## 验证

基础测试：

```bash
uv run python -m pytest -q
uv run python scripts/eval_routes.py --cases examples/eval_bank.sample.yaml --mock-embeddings
uv run python scripts/verify_route_contract.py
```

生产前 sidecar preflight：

```bash
uv run python scripts/preflight.py --router-base-url http://127.0.0.1:4001
# 如果配置了 ROUTER_INBOUND_API_KEY:
uv run python scripts/preflight.py \
  --router-base-url http://127.0.0.1:4001 \
  --intentmux-api-key "$ROUTER_INBOUND_API_KEY"
```

LiteLLM 入口 E2E：

```bash
uv run python scripts/e2e_litellm_entry.py --litellm-base-url http://127.0.0.1:4000
```

本机生产推荐继续使用 LiteLLM sidecar 入口，避免让客户端绕过既有
LiteLLM provider routing、fallback、key 和 budget 管理；开发和 CI 则要同时覆盖
direct gateway 与 sidecar 两条路径：

| 场景 | 入口 | 主要验证 |
| --- | --- | --- |
| 本机生产 | LiteLLM `:4000`，`model=semantic-router` | `e2e_litellm_entry.py` 和 rollout helper 的 legacy preflight |
| direct gateway | IntentMux `:4001/v1`，`model=auto|lite|deep` | `preflight.py --model auto`、`/v1/models` 和协议级测试 |
| sidecar 兼容 | LiteLLM model entry -> IntentMux | `tests/test_e2e_litellm_entry.py` |
| 协议回归 | IntentMux -> OpenAI-compatible upstream | `tests/test_protocol_gateway.py` |

`preflight.py` 直连 IntentMux，只在配置了 `ROUTER_INBOUND_API_KEY` 时需要
`--intentmux-api-key`。`e2e_litellm_entry.py` 通过 LiteLLM 入口验证完整链路，
需要 `LITELLM_MASTER_KEY` 或 `--api-key`。两个脚本都不会打印密钥或 prompt。

## 日志审计

IntentMux 默认有两个日志面：

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

默认不会记录 prompt、completion、token usage 或 bearer token。`request_id` 只用于跨层关联，可能来自请求头、`metadata.semantic_router_request_id`、`user` 字段，或由 IntentMux 生成。

本地灰度阶段可以显式开启单独的 prompt review log：

```bash
ROUTER_PROMPT_LOG_MODE=redacted   # 默认建议：遮盖常见 bearer/sk/base64 凭据
ROUTER_PROMPT_LOG_MODE=raw_local  # 本地私有审查：记录 latest user text 原文
```

prompt review log 写入 `ROUTER_PROMPT_LOG_DIR/YYYY-MM-DD.jsonl`，不进入 stdout、不进入普通 route audit JSONL、不进入 daily health。每条记录包含 `request_id`、`route_id`、`target_model`、`reason`、`stream` 和 `latest_user_text`，用于把 route candidate 和本地语义样本关联起来。公开部署和不可信环境应保持 `off`；开启 `raw_local` 前应确认挂载目录不会被提交、同步到云端或转发给外部系统。

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

`embedding_error` 不一定会导致请求失败，它表示 embedding 不可用后按配置降级到 fallback route，默认语义是 `lite`；生产巡检应给它独立预算。若要放宽预算，可以用 `--max-embedding-error-rate 0.02` 这类阈值保留告警能力。

日常巡检还可以要求今天的审计日志达到最低样本量，避免“没有真实流量”被误读为健康：

```bash
uv run python scripts/intentmux_daily_health.py \
  --log-dir /data/logs \
  --timezone Asia/Shanghai \
  --min-route-records 100
```

低于阈值时报告中的 `traffic_evidence.ok` 会是 `false`，脚本返回码为 `4`。
这里的样本数只统计有效 `route_complete` / `route_error` 记录，不把坏 JSON、非路由事件或其他混入日志计入流量证据。
`--timezone` 默认读取 `INTENTMUX_TIMEZONE`，未设置时使用 `Asia/Shanghai`；也可以用
`--date YYYY-MM-DD` 明确指定要巡检的审计日志日期。

daily health 还会输出 `log_consistency`，用于审计今天的 route audit log 和可选
prompt review log 是否能按 `request_id` 对齐。它会统计重复 `request_id`、缺失
`request_id`、`route_without_prompt` 和 `prompt_without_route`。这些字段用于判断日志证据
是否足够支撑 AI 复核和人工审计；prompt review log 是本地私有补充证据，因此该检查默认只写入报告，
不改变 readiness 或错误预算结论。正在处理中的请求可能已经写入 prompt review、但尚未写入
route audit；这类新近记录会计入 `prompt_recent_in_grace`，不会立即算作
`prompt_without_route`。

daily health 同时会在 `<log-dir>/quality/<YYYY-MM-DD>/` 写入质量闭环产物：
当日 route summary JSON、`current-router` 和简单 baseline eval JSON、route quality
report、review candidates，以及默认 metadata-only 的 AI review packet。它只生成通用
artifact，不调用 AI provider，也不把 raw prompt 写进默认 packet。

审计 `request_id` 来源只使用 `x-request-id`、`x-correlation-id`、`traceparent` 或
`metadata.semantic_router_request_id`。OpenAI `user` 字段可能包含真实用户标识，IntentMux 不会把它写入 audit log 的 `request_id`。

日志驱动质量闭环见 [docs/log_driven_quality_loop.md](docs/log_driven_quality_loop.md)；
当前证据状态见 [docs/route_quality_evidence_status.md](docs/route_quality_evidence_status.md)；
`dataset-pipeline-v2` 执行基线见 [docs/router_data_pipeline_research.md](docs/router_data_pipeline_research.md)。
route audit log 只负责发现低置信、异常状态码、慢请求和分布漂移；prompt review log 是显式开启的本地私有补充证据。
需要 AI 复核或人工审计的候选可以从审计日志里生成：

```bash
uv run python scripts/select_review_candidates.py /data/logs/routes/*.jsonl \
  --routes /data/config/routes.yaml \
  --prompt-path "/data/logs/prompts/*.jsonl" \
  --json-output /tmp/intentmux-review-candidates.json \
  --markdown-output /tmp/intentmux-review-candidates.md
```

候选报告只包含 `request_id`、`route_id`、`target_model`、`reason`、分数、状态码、耗时和
OpenAI-compatible 请求结构信号等元数据。启用 `--prompt-path` 时，报告只按 `request_id`
标出是否存在匹配的 prompt review 证据、是否被截断和字符数，不输出 prompt 原文，也不从
prompt 文本推断调用框架身份。
`hard_rule:*` 命中会优先进入候选报告，用来复核 `token`、`安全`、`权限` 等宽词是否过度升级。
AI 可以先做候选归纳和不确定性上浮；只有经接受、脱敏且设置 `redacted: true`
的样本才能进入 eval 或 route bank。
仓库提供通用的本地 AI review artifact 脚本：
`scripts/prepare_ai_review_packet.py` 把候选转成 AI 可读 packet，
`scripts/summarize_ai_review.py` 校验并汇总 AI 输出；脚本本身不调用任何 AI
provider，不在请求时路由路径里运行，也不依赖 Retinue、Hermes 或 OpenCode。

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
  -d '{"model":"auto","messages":[{"role":"user","content":"这个线上 bug 为什么偶发？"}]}'
```

如果启用了 `ROUTER_INBOUND_API_KEY`，加上入站鉴权头：

```bash
curl http://127.0.0.1:4001/v1/semantic-router/decision \
  -H "Authorization: Bearer $ROUTER_INBOUND_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"这个线上 bug 为什么偶发？"}]}'
```

返回内容包含 `route_id`、`target_model`、`policy_id`、`reason`、`rewrite` 和分数。
当请求通过 embedding 命中 route bank 路由时，还会返回 `match_source`、
`match_index` 和 `match_text_sha256`，用于审计“命中了哪类上游样本”。这些字段只记录
加载后的 route utterance 来源、索引和文本 hash，不返回匹配样本文本；hard rule、
显式 route、低置信 fallback 或 passthrough 会返回 `null`。
route bank YAML 里的 `source` 字段决定了这些审计字段能追到哪个上游来源。

审计一条 `deep` 请求时，先看 `/v1/semantic-router/decision` 返回：

```json
{
  "route_id": "deep",
  "policy_id": "embedding",
  "reason": "embedding",
  "match_source": "swebench_issue_resolution",
  "match_index": 12,
  "match_text_sha256": "..."
}
```

含义是：这条请求不是因为 hard rule 升级，而是 embedding 路由命中了已加载 route
utterances 中第 12 条、来源为 `swebench_issue_resolution` 的样本；`match_text_sha256`
可用于在本地 route bank 中定位具体文本，同时避免在审计日志里直接写出匹配样本文本。

## 语义资产

运行时保持轻依赖。更大的 route bank 从 `config/route_sources.yaml` 声明的来源离线生成，不把 Hugging Face 等构建依赖带进运行时。
产品控制面见 [docs/PROJECT_CONTROL.md](docs/PROJECT_CONTROL.md)；数据管线、上游语料、embedding cache
和向量库取舍见 [docs/router_data_pipeline_research.md](docs/router_data_pipeline_research.md)。

`config/route_sources.yaml` 的默认策略是“权威数据集尽量全量规范化，运行时索引分层限量”：
`ingest_all: true` 的来源会进入本地 ignored normalized records，`limit` 只控制该来源最终进入
route/eval/calibration 产物的数量。MASSIVE 这类带官方 split 的数据集按 split 接入：
train 作为 route 候选，dev/test 作为 eval/calibration 候选。少量 `curated_yaml`
只作为公开、脱敏的简体中文复杂意图 seed/overlay，不是长期替代权威数据集的手工流程。

仓库默认只跟踪 example 基线：

- `examples/route_bank.sample.yaml`：可运行的公开 route-bank 示例，`lite`
  展示 MASSIVE zh-CN general utterances，`deep` 展示 SWE-bench / HumanEval 类代码任务。
- `data/source_samples/default_zh_cn_deep.example.yaml`：少量公开、脱敏、通用的简体中文
  `deep` seed，只用于补足默认中文复杂意图覆盖；正式语义资产仍应离线生成并留在运行时目录。
- `examples/eval_bank.sample.yaml`：可运行的 `lite` / `deep` regression 示例，用于
  clean clone、CI 和文档演示。
- `config/eval_cases.yaml`：小型 smoke/regression suite，不再作为默认质量基线。

正式生成的 `data/semantic_sets/route_bank.yaml`、`data/semantic_sets/eval_bank.yaml`、
`data/semantic_sets/calibration_bank.yaml` 和
`data/semantic_sets/normalized/*.jsonl` 是本地/生产资产，默认被 git 忽略。
`intentmux_daily_health.py` 会优先使用正式 route/eval 资产；如果不存在，则退回到
`examples/*.sample.yaml`，保证新用户 clone 后仍能跑通工具链。

```bash
uv sync --group assets
uv run python scripts/build_semantic_assets.py
```

`scripts/build_semantic_assets.py` 会从 `config/route_sources.yaml` 生成 normalized
records，并按 `intended_use` 分流到 route bank、eval bank 和 calibration bank。
旧的 `scripts/build_route_bank.py` / `scripts/build_eval_bank.py` 仍可用于 bootstrap
和兼容流程，但新的质量基线应优先走 `dataset-pipeline-v2`。

生成文件默认不进 git。生产 review 样本必须先脱敏，再导入 eval：

```bash
uv run python scripts/import_review_samples.py \
  --input data/source_samples/production_review.redacted.jsonl \
  --output data/semantic_sets/production_review_eval_cases.yaml \
  --routes config/routes.yaml
```

每条 JSONL 必须设置 `redacted: true`，并用 route id 作为 `expect`。
安全示例见 [data/source_samples/production_review.example.jsonl](data/source_samples/production_review.example.jsonl)。
真实 review JSONL 默认被 `.gitignore` 排除；只提交公开样例，不提交本地生产复核样本。

生成质量报告的推荐流程。生产环境优先使用本地生成或挂载的
`data/semantic_sets/eval_bank.yaml`，用于确认公开 route bank 已进入路由索引，并和简单
baseline 做回归对比；clean clone 可使用 `examples/eval_bank.sample.yaml` 跑通流程。
这些仍不是完整中文语义路由 benchmark，不能单独证明泛化质量。`config/eval_cases.yaml`
只保留为更小的 smoke/regression suite。
生产质量判断应优先使用当天或迁移到 `lite` / `deep` 之后的日志，避免旧
`fast` / `strong` 记录污染当前策略判断。

```bash
uv run python scripts/eval_routes.py \
  --cases data/semantic_sets/eval_bank.yaml \
  --mock-embeddings \
  --baseline current-router \
  --json-output /tmp/intentmux-eval-current.json
uv run python scripts/eval_routes.py \
  --cases data/semantic_sets/eval_bank.yaml \
  --mock-embeddings \
  --baseline always-lite \
  --json-output /tmp/intentmux-eval-always-lite.json || true
uv run python scripts/eval_routes.py \
  --cases data/semantic_sets/eval_bank.yaml \
  --mock-embeddings \
  --baseline always-deep \
  --json-output /tmp/intentmux-eval-always-deep.json || true
uv run python scripts/eval_routes.py \
  --cases data/semantic_sets/eval_bank.yaml \
  --mock-embeddings \
  --baseline hard-rule-only \
  --json-output /tmp/intentmux-eval-hard-rule-only.json || true
uv run python scripts/router_log_summary.py /data/logs/routes/*.jsonl --json > /tmp/intentmux-routes.json
uv run python scripts/route_quality_report.py \
  --eval-json current=/tmp/intentmux-eval-current.json \
  --eval-json always-lite=/tmp/intentmux-eval-always-lite.json \
  --eval-json always-deep=/tmp/intentmux-eval-always-deep.json \
  --eval-json hard-rule-only=/tmp/intentmux-eval-hard-rule-only.json \
  --route-summary-json /tmp/intentmux-routes.json \
  --route-bank data/semantic_sets/route_bank.yaml \
  --json-output /tmp/intentmux-quality.json \
  --markdown-output /tmp/intentmux-quality.md
```

RouteLLM 风格的阈值/成本质量校准报告使用独立 thin script，不修改生产路由：

```bash
uv run python scripts/route_calibration_report.py \
  --cases data/semantic_sets/eval_bank.yaml \
  --work-dir .intentmux-home/quality-spikes/route-calibration \
  --json-output /tmp/intentmux-route-calibration.json \
  --markdown-output /tmp/intentmux-route-calibration.md \
  --mock-embeddings \
  --thresholds 0.35,0.45,0.55,0.65,0.75
```

输出包含 baseline comparison、threshold curve、slice metrics、coverage 和
recommendation。它只用于判断 scorer、route bank 或 threshold 变化是否值得继续，
不会自动修改生产配置。

`always-lite`、`always-deep` 和 `hard-rule-only` baseline 可能故意返回非零退出码，
因为它们会输掉一部分 regression cases；只要 JSON 已生成，就可以进入质量报告对比。
轻量质量闭环的当前工作顺序以 [docs/PROJECT_CONTROL.md](docs/PROJECT_CONTROL.md)
为准；归档计划只作为历史背景，不作为执行入口。

生产变更必须先通过 [docs/production_rollout_gate.md](docs/production_rollout_gate.md)，不要在探索阶段直接重启或重建生产 sidecar。
任何 route bank、阈值、margin 或 hard rule 变更，都应附带本报告作为审计证据。

Agent 框架接入建议见 [docs/agent_framework_integration.md](docs/agent_framework_integration.md)。代码编辑、工具调用、PR review、生产事故和安全分析等高风险负载建议显式发送 `model=deep` 或 `metadata.route_id=deep`，不要完全依赖低置信 fallback。

## 运行行为

推荐把 IntentMux 作为 LiteLLM compose project 里的并列 sidecar，而不是塞进 LiteLLM 挂载目录或服务内部。

- Docker health 使用 `/health`，避免 readiness 抖动触发重启循环。
- `/ready` 检查 router、LiteLLM、embedding 三层。
- embedding 不可用时，聊天请求 fail-open 到 `fallback_route_id`，并记录 `reason=embedding_error`。
- LiteLLM/upstream `5xx` 或连接异常 fail-closed 为脱敏 `502`，并记录 `route_error`。
- LiteLLM/upstream `4xx` 默认按代理语义透传，但审计日志记录 `ok=false` / `outcome=upstream_non_200`。

## 当前能力

IntentMux 已具备基本路由、preflight、LiteLLM-entry E2E、结构化日志和 error-budget gate，适合在本地或私有网关环境中做轻量意图分流验证。
