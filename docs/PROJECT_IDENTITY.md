# 项目身份

此文件只保留给 agent 的短事实。面向人的说明以中文 README 为准。

- 项目名：`IntentMux`
- Python 包名：`intentmux`
- 运行时代码命名空间：`router`
- 公开入口模型：`auto`、`lite`、`deep`
- LiteLLM sidecar 兼容入口：`semantic-router`
- 本地默认容器/compose service：`intentmux`
- 本地默认镜像 tag：`intentmux:local`

边界：

- IntentMux 是 OpenAI-compatible 路由网关，不是模型供应商。
- IntentMux 可以独立连接任意 OpenAI-compatible upstream。
- LiteLLM-first 部署里，LiteLLM 仍负责 provider routing、fallback、keys、budgets、model pools。
- `/v1/models` 只应广告 `auto`、`lite`、`deep`，不广告本地 upstream model group。
