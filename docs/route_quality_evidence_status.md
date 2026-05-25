# 路由质量证据状态

这份文档只记录当前状态，不再承载下一步方案。当前方案入口见：

```text
docs/PROJECT_CONTROL.md
docs/router_data_pipeline_research.md
docs/log_driven_quality_loop.md
```

## 当前结论

IntentMux 的协议、日志、候选筛选和质量报告框架已经可用；路由质量证据仍不足。

当前路由机制：

```text
显式 route override
  -> 非入口模型 passthrough
  -> hard rule 升级
  -> Aurelio semantic-router 内核对 lite/deep route examples 做 hybrid 匹配
  -> 低置信 fallback 到 lite
```

Aurelio 覆盖的是成熟路由内核，不是 IntentMux 的完整产品语义。它提供
route/utterance 抽象、dense/hybrid matching、本地 index 和 score；IntentMux
仍负责 OpenAI-compatible / LiteLLM sidecar 或 gateway、`lite` / `deep` 两档
模型语义、配置、日志、审计、健康检查、生产质量报告和本地学习闭环。

公开仓库只提交小型示例资产和源清单。正式 route/eval/calibration semantic sets
是本地或生产运行时资产，默认不进 git；当前数量应以 live `/ready`、运行时
semantic set 文件或 `scripts/inspect_semantic_assets.py` 为准。

现有公开来源已经能支撑 dogfood、回归和离线校准形状，但仍不足以单独证明中文
语义路由质量。中文 deep 和边界样本仍应优先来自成熟公开数据或经过脱敏审查的
代表性回归样本。

## 已实现证据能力

- route audit log 和 prompt review log 分离；
- daily health 生成 route summary、baseline eval、quality report、review candidates、AI review packet；
- `route_quality_report.py` 支持 baseline 对比和产品指标；
- embedding 决策暴露 `match_source`、`match_index`、`match_text_sha256`、
  `match_score`、`match_provenance`；
- Aurelio hybrid 模式下 `match_provenance=aurelio_hybrid_exact` 表示审计字段
  来自与 hybrid scoring 一致的本地样例匹配，而不是同 route 内的 dense-only
  近似归因；
- `match_source=inline_config` 表示命中的是当前 `routes.yaml` 内联种子样例，
  不是上游 route-bank 数据集；
- `examples/*.sample.yaml` 可运行，正式 `data/semantic_sets/*.yaml` 默认不进 git；
- route-bank embedding vectors 会写入运行时 cache，并在 route bank 或 embedding
  model 变化时失效。

## 未闭环

- 公开 evidence 仍不能覆盖所有通用中文 deep 场景；
- threshold / margin 变化仍需要重复、代表性的 before/after 报告；
- AI review 结果尚未形成稳定的接受/拒绝/回灌门禁；
- 生产质量报告还需要长期、固定地驱动路由策略变更。

## 下一步判断

下一步不应先改路由算法，也不应直接把所有上游数据塞进运行时。默认进入日志驱动
维护：只有日志、replay、eval 或 calibration report 显示重复模式时，才推进
route bank、hard rule、threshold 或 margin 变化。

公开数据方向继续以 `docs/router_data_pipeline_research.md` 为基线：成熟来源、
route/eval/calibration 分层、slice metadata、embedding cache 和 before/after
quality gate。
