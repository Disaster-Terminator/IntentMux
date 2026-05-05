# Project Identity

本文档记录当前项目名、仓库 metadata 建议，以及为什么产品名和默认 LiteLLM 入口名分开。

## 当前产品名

```text
IntentMux
```

中文定位：

```text
轻量、可审计的 LiteLLM 意图分流 sidecar。
```

英文定位：

```text
Lightweight, auditable intent router for LiteLLM and OpenAI-compatible model gateways.
```

## 为什么是 IntentMux

项目的核心不是“又一个模型提供商”，也不是替代 LiteLLM 的完整调度层，而是在现有
OpenAI/LiteLLM-compatible 入口前做轻量意图分流：

```text
request intent -> route_id -> target_model -> LiteLLM model group
```

`IntentMux` 的优势：

- `Intent` 说明决策依据来自请求意图，而不是固定 provider 或静态 model alias。
- `Mux` 暗示 multiplexing / demultiplexing，工程语义清楚，适合 gateway sidecar。
- 名字短，读者能大致猜到用途，不需要像 `Cynosure` 一样额外解释。
- 不被 `semantic` 这个单一实现方式绑定；未来 hard rules、metadata override、
  embedding、eval、observability、error budget 都能放在同一控制面下。

## 不采用的候选

### Cynosure Router

不采用。它有品牌感，但词义生僻，解释成本高，不符合本项目“轻量、本地、快速部署”的气质。

### RouteLens

不采用。它更像路由观测工具，不能准确表达“执行前分流”。同时已有相近命名和相近语境使用痕迹，
撞名/混淆风险高。

### SignalRoute

可作为保守备选，但偏普通，记忆点不如 `IntentMux`。

### gateway-semantic-router

保留为当前仓库路径/历史名称，不作为产品名继续强化。它过于描述性，也容易和 LiteLLM 原生
smart-router 或 generic semantic routing 概念混淆。

## 产品名与入口名分离

默认 LiteLLM 模型入口仍建议保留：

```text
semantic-router
```

原因：

- 这是当前低侵入接入面的协议入口：客户端保持打 LiteLLM，只改模型名。
- 已经有本机配置、E2E、日志和文档围绕 `model=semantic-router` 验证。
- 改产品名不应该强迫用户同步修改运行时入口。

因此当前语义是：

```text
Product name: IntentMux
LiteLLM entry model: semantic-router
Python package/module: router
GitHub repository name: IntentMux
Current local path: /home/raystorm/gateway/gateway-semantic-router
```

## GitHub metadata 建议

Repository display/title:

```text
IntentMux
```

About description:

```text
Lightweight, auditable intent router for LiteLLM and OpenAI-compatible model gateways.
```

Topics:

```text
llm-gateway
litellm
openai-compatible
model-routing
intent-routing
semantic-routing
agent-infra
observability
```

GitHub repository 已改名为 `IntentMux`。当前本地目录和 Docker compose build context 仍保留
`gateway-semantic-router`，因为它们反映本机部署状态，改本地路径会影响 compose、agent 和历史文档上下文。

## 迁移注意事项

如果未来继续统一本地路径或服务名，需要同步检查：

- README 中的本地路径示例；
- compose build context；
- Docker service name；
- CI badge 或 workflow 文案；
- 外部脚本、Codex / agent 配置里的 repo URL；
- 本地 clone 路径；
- LiteLLM compose 中指向 sidecar 的路径或服务名。

当前 README 使用 `IntentMux` 作为产品名，同时保留部分本地路径示例，例如：

```text
/home/raystorm/gateway/gateway-semantic-router
```

这些路径反映当前部署状态。后续若统一本地目录名，应作为单独迁移处理。
