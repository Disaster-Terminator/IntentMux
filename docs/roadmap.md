# 路线图

当前路线图以 `docs/PROJECT_CONTROL.md` 为准。本文只保留面向人的短摘要。

## 长期目标

IntentMux 是轻量 OpenAI-compatible `intentmux` / `lite` / `deep` 路由网关：

- 可作为独立 gateway 连接任意 OpenAI-compatible upstream；
- 可作为 LiteLLM-first sidecar，保留 LiteLLM 的 provider routing、fallback、keys、budgets；
- 路由质量由数据管线、eval、日志和质量报告驱动，而不是手写猜测；
- 默认运行时保持轻量，数据集构建和 embedding cache 属于离线/本地资产。

## 当前优先级

1. 保持生产服务稳定，所有生产变更走 rollout gate。
2. 默认冻结路由行为，用日志、replay、eval 和 calibration report 驱动小步变化。
3. 继续用成熟公开数据维护 route/eval/calibration 分层证据。
4. 用日志候选和 AI review packet 降低私有审查成本。
5. 只有 before/after quality report 显示收益时，才调整 route bank、hard rules、threshold 或 margin。
