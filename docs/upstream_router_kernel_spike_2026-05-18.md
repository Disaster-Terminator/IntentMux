# 上游路由内核调研快照

日期：2026-05-18

## 背景

当前 IntentMux 已经具备本地 sidecar/gateway 壳层、LiteLLM 低侵入接入、日志、巡检、runtime home、健康检查和基础路由审计。但当前自研路由内核只是：

```text
hard rule -> request embedding -> route-bank cosine similarity -> threshold/margin -> lite fallback
```

这接近成熟 semantic router 的最小子集。继续沿这个方向扩展，存在重复造轮子风险。当前快照已保存到远端分支：

```text
snapshot/self-built-router-20260518 -> f60ea51
```

后续主线必须先做上游内核 spike，再决定如何用成熟 Python 包替换自研路由内核。

## 不可妥协的产品边界

IntentMux 的价值不应是“自研相似度算法”，而是成熟路由能力的本地中文优先产品化：

- 本地轻量，默认不要求重型向量数据库、Kubernetes 或额外控制面；
- LiteLLM-first，同时保留 OpenAI-compatible gateway/sidecar 形态；
- 两档产品语义：`lite` / `deep`；
- 中文优先，英文不落后；
- 语义资产可审计，可解释某条请求为什么被路由；
- 可学习：本地日志和 review 产物能形成候选样本、校准数据、回归用例；
- 学习默认发生在本地，进入公共默认基线必须经过筛选和许可证审查。

## 调研候选池

### vLLM Semantic Router

定位：系统级 signal-driven router / gateway / control-plane。

证据：

- 项目自述为 “System Level Intelligent Router for Mixture-of-Models at Cloud, Data Center and Edge”。
- 许可证为 Apache-2.0。
- 最新配置形态是 canonical YAML，按 `listeners`、`providers`、`routing`、`global` 切分。
- `routing` 下有 `modelCards`、`signals`、`projections`、`decisions`；`providers` 下管理模型和后端绑定。
- 官方博客强调 intent-aware routing、reasoning budget、tool calling constraints、Envoy/Kubernetes/gateway integration。

初步判断：

- 它是最接近“成熟系统级路由产品”的候选。
- 但默认形态可能明显重于 IntentMux 当前本地 sidecar。
- 适合重点调研：是否能作为配置/信号/决策架构参考。
- 不应在未跑通本机最小 demo 前直接迁移主线。

### Aurelio Semantic Router

定位：轻量 semantic route library。

证据：

- 核心概念是 `Route`、encoder、`SemanticRouter`。
- 支持本地 `HuggingFaceEncoder`，也支持 OpenAI/Cohere/FastEmbed/Azure 等 encoder。
- 支持 route threshold optimization：通过 `fit(X, y)` 优化每个 route 的 threshold，并通过 `evaluate(X, y)` 评估。
- 文档明确 threshold 不应手调，应该用样本拟合和评估。

初步判断：

- 它最接近我们当前“route examples + embedding + threshold”的内核问题。
- 适合优先做 Python dependency adapter spike。
- 风险是它偏分类库，不负责 LiteLLM/OpenAI-compatible gateway、日志、runtime、巡检。
- 如果 adapter 能满足 provenance、阈值校准和本地 index，IntentMux 自研内核应降级为 fallback。

### RouteLLM

定位：强/弱模型成本质量路由和评估框架。

证据：

- 项目目标是 serving and evaluating LLM routers。
- 提供 OpenAI client/server 替换形态，用 router 在强弱模型之间分流。
- 官方 README 声称预训练 router 可降低成本，同时保持接近强模型性能。
- PyPI 文档提供 `calibrate_threshold`，通过 high-capability route percentage 校准 router threshold。

初步判断：

- 它最适合作为 `lite` / `deep` 成本质量评估和 threshold calibration 方法来源。
- 不一定适合作为中文 route-bank 语义分类内核。
- 更可能是 methodology-only 或 eval/calibration adapter。

## 决策矩阵

候选必须按证据打分，不能按印象选择。

| 维度 | 说明 | 必须验证的证据 |
| --- | --- | --- |
| 产品贴合 | 是否支持本地两档 `lite` / `deep` 路由 | 最小 demo 可以把同一批请求分到两档 |
| LiteLLM 接入 | 是否能低侵入接入当前 4000/4001 形态 | OpenAI-compatible chat/completions 或 adapter demo |
| 本地轻量 | 是否能在本机长期运行，不额外引入重服务 | 安装体积、常驻进程、CPU/RAM、启动时间 |
| 中文能力 | 是否能加载中文语料并做合理路由 | 简体中文 route/eval 样本跑通 |
| 英文不落后 | 是否能复用英文成熟样本/benchmark 方法 | 英文 route/eval 样本跑通 |
| 可学习 | 是否能导入本地 review 样本、校准阈值或更新 route examples | 离线 import/calibration demo |
| 可审计 | 是否能输出 route reason、score、threshold、match provenance | 单条请求可解释输出 |
| 维护成本 | 是否能正常依赖上游 Python 包并跟随更新 | 语言栈、依赖、release 节奏、patch 面 |
| 许可证 | 能否和 Apache-2.0 IntentMux 兼容 | LICENSE 和依赖许可记录 |

## Spike Gates

每个候选的 spike 必须产生可审计产物：

1. `install.md` 或命令记录：如何本机安装、是否污染全局环境。
2. `demo_config.*`：表达 `lite` / `deep` 两档。
3. `demo_requests.jsonl`：中英文、代码/debug、安全、普通短任务、agent 工具流量样本。
4. `demo_result.json`：包含 route、score/threshold 或等价决策证据、耗时。
5. 适配判断：`default dependency`、`adapter`、`methodology-only`、`reject` 四选一。

## Adapter / Dependency 规则

默认顺序：

```text
default dependency/adapter > self-built fallback
```

选择 dependency/adapter，当：

- 上游库能在 Python 内被调用；
- 能保留 IntentMux 的 OpenAI-compatible 壳层；
- 能输出足够审计信息；
- 不要求用户运行额外重服务。

选择 methodology-only，当：

- 上游方法正确，但产品形态太重或目标不同；
- 适合作为 eval、threshold calibration、signal/decision DSL 参考。

保留 self-built fallback，当：

- 成熟候选都无法满足本地轻量或接入边界；
- 或成熟候选需要网络/GPU/重依赖，不能作为默认路径。

## 交叉验证结论

一次性高阶 Codex 交叉验证给出的修正是：不要先急着替换 scoring
library。更稳的顺序是先把评估/校准框架做成成熟项目形态，再验证
adapter。原因是没有本地 bilingual eval/calibration harness 时，任何
“上游内核更好”的判断都不可审计。

Retinue 低成本子代理在本轮调研中出现 `provider_blank_assistant` stalled，
没有产出可采信结论。因此本文件当前只采用主代理检索到的官方资料和高阶
Codex 交叉验证结论；Retinue 结果不作为证据。

## 当前推荐的调研顺序

1. **RouteLLM methodology / calibration spike**  
   目的：先把 IntentMux 的质量判断变成成熟路由项目形态：`always-lite`、
   `always-deep`、current-router、rule-only、embedding-only、threshold
   curve、`deep` call rate、slice metrics。没有这层，adapter 的收益
   无法证明。

   当前入口：`scripts/route_calibration_report.py`。它生成
   `intentmux-route-calibration-v1` JSON 和 Markdown，包含 baseline
   comparison、threshold curve、slice metrics、coverage 和 recommendation。
   产物默认写到 ignored runtime/work 目录；报告只提供证据，不修改生产配置。

2. **Aurelio Semantic Router adapter spike**  
   目的：验证是否能用成熟 route/encoder/index/threshold optimization
   替换当前 cosine route-bank 内核，同时保留 IntentMux 的 API、日志、
   runtime home 和 LiteLLM 边界。

   当前产物：`docs/upstream/aurelio_semantic_router_adapter_fit_2026-05-19.md`。
   结论已更新为：Aurelio Python 包是默认路由依赖，默认形态为
   `HybridRouter + HybridLocalIndex`；`basic` 只保留为 fallback/debug baseline。

3. **vLLM Semantic Router architecture / product-fit spike**  
   目的：验证是否值得学习其 signal/projection/decision/provider
   配置形态。重点看是否能压缩成本地轻量 sidecar，而不是照搬 Envoy /
   Kubernetes / control-plane 复杂度。

   当前产物：`docs/upstream/vllm_semantic_router_architecture_fit_2026-05-19.md`。
   结论是 methodology-only / architecture reference。短期学习
   signal/projection/decision 分层和审计链，不引入运行时依赖。

## 当前主线约束

- 不再继续扩展当前自研 routing engine 为主内核。
- 不再靠手工增加几百条 YAML 来证明质量。
- 旧实现保留为 `basic` baseline/fallback。
- 所有新方向必须有 spike 结果、评分矩阵和可复现实验输出后才能进入主线。

## 上下文保存规则

为了避免上下文丢失：

- 每轮调研只追加本文件或新建一个小型 spike 产物；
- 大型原始日志、下载数据、demo 输出必须写到 ignored runtime/data 目录；
- 对话中只汇报结论、路径和关键证据；
- 重要转向必须先 commit 再继续下一阶段。

## 参考资料

- vLLM Semantic Router introduction:
  https://vllm-semantic-router.com/docs/intro/
- vLLM Semantic Router configuration contract:
  https://vllm-semantic-router.com/docs/installation/configuration/
- vLLM Semantic Router GitHub:
  https://github.com/vllm-project/semantic-router
- Aurelio Semantic Router introduction:
  https://docs.aurelio.ai/semantic-router/get-started/introduction
- Aurelio Semantic Router architecture:
  https://docs.aurelio.ai/semantic-router/user-guide/concepts/architecture
- Aurelio threshold optimization:
  https://docs.aurelio.ai/semantic-router/user-guide/features/threshold-optimization
- RouteLLM GitHub:
  https://github.com/lm-sys/RouteLLM
- RouteLLM PyPI:
  https://pypi.org/project/routellm/
