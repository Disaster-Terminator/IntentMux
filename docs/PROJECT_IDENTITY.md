# Project Identity Proposal

本文档记录仓库名称、GitHub 标题和 About 描述建议。此文件只是项目内文档，不会修改 GitHub 仓库元数据。

## 推荐名称

```text
Cynosure Router
```

## 推荐仓库名

```text
cynosure-router
```

保留 `router` 后缀是为了降低识别成本：项目本质仍然是 LLM gateway 前面的 routing sidecar。`Cynosure` 提供品牌识别，`Router` 提供功能锚点。

不建议继续使用：

```text
gateway-semantic-router
```

原因：

- 名字过于描述性，缺少产品识别度；
- `semantic-router` 容易和 LiteLLM / 其他项目里的 generic semantic routing 概念混淆；
- 无法表达本项目真正的差异点：中文-heavy agent traffic、可审计结构化日志、decision preview、error budget gate、LiteLLM 控制面 sidecar；
- 未来如果加入 response/chat-completion shim、route quality workflow、traffic audit 等能力，旧名会显得过窄。

## GitHub repository title 建议

```text
Cynosure Router
```

## GitHub About description 建议

```text
Intent-aware model routing sidecar for LiteLLM/OpenAI-compatible gateways, built for Chinese-heavy agent traffic, auditable decisions, and safe fallback.
```

备选短版：

```text
Auditable intent router for LiteLLM and OpenAI-compatible model gateways.
```

## 一句话定位

```text
Cynosure Router is the intent-aware control plane that decides where model traffic should go before LiteLLM executes it.
```

中文版本：

```text
Cynosure Router 是 LiteLLM 执行模型前的一层意图分流控制面。
```

## 命名理由

`Cynosure` 原意接近“指引方向的中心点”。这个词适合本项目，因为项目本身不执行模型、不管理 provider，也不替代 LiteLLM，而是在流量进入执行层前给出方向：

```text
intent → route_id → target_model → auditable rewrite
```

这个名字比 `gateway-semantic-router` 更适合长期演进：

- 不被 `semantic` 这个单一实现方式绑定；
- 不和 LiteLLM 原生 `smart-router` 或其他 semantic router 概念打架；
- 能容纳 hard rules、metadata override、embedding、eval、observability、error budget 等多种控制面能力；
- 有品牌感，但仍然通过 `Router` 保留功能可读性。

## 建议的 README 标题结构

```markdown
# Cynosure Router

> 面向 LLM Gateway 的意图分流控制面。  
> Intent-aware routing sidecar for LiteLLM / OpenAI-compatible gateways.
```

## 建议的后续平台元数据修改

当本 PR 合并并确认文档方向后，可手动修改 GitHub 平台元数据：

- Repository name: `cynosure-router`
- Repository title / display name: `Cynosure Router`
- About description: 使用本文推荐长版或短版
- Topics 可考虑：
  - `llm-gateway`
  - `litellm`
  - `openai-compatible`
  - `model-routing`
  - `semantic-routing`
  - `agent-infra`
  - `observability`

本 PR 不执行这些平台级修改。

## 迁移注意事项

如果后续真正重命名仓库，需要同步检查：

- README 中的本地路径示例；
- compose build context；
- Docker service name；
- CI badge 或 workflow 文案；
- 外部脚本、Codex / agent 配置里的 repo URL；
- 本地 clone 路径；
- LiteLLM compose 中指向 sidecar 的路径或服务名。

当前 README 仍保留部分本地路径示例，例如：

```text
/path/to/gateway/gateway-semantic-router
```

这些路径反映当前部署状态。仓库真正重命名后，再统一改为新的本地目录名会更安全。
