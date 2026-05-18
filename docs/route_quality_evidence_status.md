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
  -> lite/deep route examples 的 embedding 相似度判断
  -> 低置信 fallback 到 lite
```

当前权威本地 route bank 是 `bootstrap-v1`，共 280 条：

| route | source | count |
| --- | --- | ---: |
| lite | MASSIVE zh-CN general | 80 |
| lite | MASSIVE zh-TW general | 40 |
| deep | SWE-bench issue resolution | 80 |
| deep | MBPP code generation | 40 |
| deep | HumanEval code generation | 40 |

这足够 dogfood 和验证数据管线形状，但不足以证明中文语义路由质量。

## 已实现证据能力

- route audit log 和 prompt review log 分离；
- daily health 生成 route summary、baseline eval、quality report、review candidates、AI review packet；
- `route_quality_report.py` 支持 baseline 对比和产品指标；
- embedding 决策暴露 `match_source`、`match_index`、`match_text_sha256`；
- `examples/*.sample.yaml` 可运行，正式 `data/semantic_sets/*.yaml` 默认不进 git。

## 未闭环

- route/eval/calibration 数据规模太小；
- eval cases 缺少完整 slice metadata；
- threshold / margin 没有基于代表性数据校准；
- embedding vectors 没有持久 cache；
- AI review 结果尚未形成稳定的接受/拒绝/回灌门禁；
- 生产质量报告还没有长期、固定地驱动路由策略变更。

## 下一步判断

下一步不应先改路由算法，也不应直接把所有上游数据塞进运行时。应按
`docs/router_data_pipeline_research.md` 设计 `dataset-pipeline-v2`：

- 扩大成熟上游数据；
- 区分 route bank、eval bank、calibration bank；
- 加入 slice metadata；
- 持久化 embedding cache；
- 用 before/after quality report gate 任何 route bank、hard rule、threshold 或 margin 变更。
