# 路由质量证据状态

这份文档记录 IntentMux 当前路由质量证据的真实状态，避免以后把计划、愿景或脚手架误认为已经完成的生产验证。

当前产品控制面见：

```text
docs/PROJECT_CONTROL.md
```

如果旧计划和本文或控制面冲突，优先相信控制面和当前事实证据。

## 摘要

IntentMux 当前已经有一套可运行的轻量路由机制：

```text
显式 route override
  -> 非入口模型 passthrough
  -> 高精度 hard rule 升级
  -> 基于 lite/deep route examples 的 embedding 相似度判断
  -> 低置信 fallback 到 lite
```

这个机制和项目定位是匹配的：轻量、本地优先、成本优先、两档路由。但它的质量还没有被足够多、足够代表性的样本证明。当前状态更准确地说是：**本机 dogfood 可用，质量开发仍然证据不足**。

## 计划与落地状态

| 能力 | 计划是否覆盖 | 仓库是否实现 | 是否已有生产级质量证据 |
| --- | --- | --- | --- |
| 足够大的代表性 eval set | 是 | 部分 | 否 |
| 按 slice 看质量 | 是 | 部分 | 否 |
| before/after quality report | 是 | 部分 | 还未成为固定闭环 |
| deep call rate + 质量指标 | 是 | 部分 | 还未成为固定闭环 |
| AI 辅助 review 样本持续回灌 | 是 | 部分 | 只有早期本地 artifacts |
| threshold / margin 系统校准 | 是 | 只有候选发现 | 否 |
| baseline 对比 | 已识别为必要项 | 已有脚本能力 | 还未成为固定闭环 |

## 当前生产证据

本机生产 runtime 当前使用挂载目录里的外部 route bank：

```text
/path/to/intentmux-runtime/semantic_sets/route_bank.yaml
```

仓库 example 和本机 runtime route bank 都已经包含成熟公开来源：

- `lite`：MASSIVE zh-CN / zh-TW general utterances。
- `deep`：SWE-bench、MBPP、HumanEval 的代码类 prompts。

所以要严格区分两件事：

- **开源数据已经用于可运行 example route bank 和本机 runtime route bank。**
- **example eval bank 已经能验证这些公开样本进入路由索引。**
- **这还不是生产质量判断 gate，也不能证明中文泛化质量。**

仓库跟踪的公开 eval example 是：

```text
examples/eval_bank.sample.yaml
```

正式生成的 `data/semantic_sets/eval_bank.yaml` 是本地/生产资产，默认不进 git。它可由
`scripts/build_eval_bank.py --per-route-limit 100` 从 smoke cases 和正式 route bank 生成。
example 和正式 eval bank 都比旧的 `config/eval_cases.yaml` 更适合作为路由数据进入索引的
回归证据，但仍不足以衡量中文泛化质量，也不足以单独调 threshold / margin。因此任何质量报告都应把它称为
regression baseline，而不是 benchmark 结论。
生产日志分析也应优先使用当天或迁移到 `lite` / `deep` 之后的日志；全历史日志里可能混有
旧 `fast` / `strong` route id，只适合作为背景上下文。

## 开源 eval 状态

仓库已经在下面文件声明中文 eval 来源候选：

```text
config/zh_route_eval_sources.yaml
```

当前 slice 设计包括：

- `lite_general_zh`
- `lite_intent_zh`
- `deep_code_zh`
- `deep_reasoning_zh`
- `deep_long_context_zh`
- `high_risk_zh`
- `borderline_zh`

这个 manifest 也记录了 license、是否可再分发、是否允许派生 prompt、commit policy 等边界。部分中文 benchmark 候选是 `manifest_only` 或 `manual_review_required`，不能直接把原始或派生数据提交进公开 route bank。

当前 builder：

```text
scripts/build_zh_route_eval.py
```

可以校验 curated samples，并保留 slice metadata。但它还没有真正下载或转换 C-Eval、CMMLU、LongBench、DataCLUE、SuperCLUE-Code3 等公开中文 benchmark，形成可运行的 eval bank。

因此当前事实是：**开源来源已经被声明，部分开源数据已经用于 route bank example、
runtime route bank 和 regression eval；但中文 benchmark 级 eval 还没有真正进入生产质量闭环。**

## 指标能力

`scripts/route_quality_report.py` 已经能在拿到 JSON eval output 后生成有用的产品指标：

- `lite_general_keep_rate`
- `lite_precision`
- `deep_recall_high_risk`
- `deep_recall_code`
- `low_confidence_rate`
- `hard_rule_hit_rate`
- `deep_call_rate`
- `near_margin_rate`
- long-context metadata coverage

这个方向是对的，但这些指标的质量取决于 eval cases 的质量。当前 eval 样本太少，所以报告只能算 regression check，不能算可靠质量测量。

## 本地数据限制

本地 dogfood 数据很有价值，因为它来自真实流量；但它也有明显限制：

- 大部分流量来自单一操作者。
- 很多请求来自 OpenCode、Retinue、Hermes 等本地 agent 工作流。
- 分布不能代表所有用户。
- raw prompt review logs 是本地私有证据，不能提交到公开仓库。
- route audit logs 能发现候选，但样本进入 eval 前仍然需要 AI 复核、必要人工审计和脱敏。

所以本地日志可以驱动近期改进，但不能单独证明通用路由质量。

## baseline 对比状态

项目现在已经能把当前 router 和简单 baseline 放到同一批 regression cases 上对比：

- always route to `lite`
- always route to `deep`
- hard-rule only
- hard-rule + embedding + current fallback

这个对比很重要。成熟路由项目通常不会只报告当前策略是否能跑，而是衡量它相对简单策略是否真的改善了成本/质量权衡。
baseline 报告已经接入 daily health quality artifacts，但还没有用足够代表性的
production review 样本做固定闭环。因此它是“每日可生成的回归对比工具”，不是“生产质量已经被证明”。

当前轻量质量闭环工作顺序见：

```text
docs/PROJECT_CONTROL.md
```

## 校准状态

当前 threshold 和 margin 是运行默认值：

```text
threshold: 0.55
margin: 0.04
```

系统现在能发现 near-threshold 和 near-margin 候选，但还没有基于代表性标注集拟合或校准这些数值。因此 threshold / margin 变更必须有 before/after quality report，不能凭直觉调整。

## 下一步

下一阶段不应该先改路由算法，而应该先建立可信的测量闭环。这里的“学习”不是
大规模手工标注，也不是把 AI 生成标签当最终真值；它是 AI 优先审查候选、脚本校验
隐私/结构/baseline、人类只处理需要决策的升级点：

1. 优先从当前生产日志生成候选和 AI review packet。
2. 让 AI 产出结构化判断和不确定性摘要。
3. 人类只审查会改变策略、涉及隐私、或 AI 不确定的情况。
4. 只把已接受、已脱敏、可解释的样本转为 regression cases。
5. 在同一批 cases 上运行当前 router 和简单 baselines。
6. 生成包含 slice metrics 和 `deep_call_rate` 的 route-quality report。
7. 再决定是否调整 route bank、hard rules、threshold 或 margin。

这样可以保持 IntentMux 的轻量定位，同时借鉴成熟路由项目重视 benchmark、baseline 和成本/质量权衡的工程纪律。
