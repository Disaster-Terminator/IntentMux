# Aurelio Semantic Router Adapter Fit

日期：2026-05-19

## 结论

Aurelio Semantic Router 适合作为 IntentMux 的 **adapter candidate**，但当前只能
先按 **methodology-first** 采纳，不适合现在 fork，也不应直接替换主线依赖。

推荐判断：

```text
methodology-first now -> adapter spike -> pass gates 后再考虑 optional dependency
```

它和 IntentMux 当前自研内核的问题域高度重合：`Route` / utterances / encoder /
index / threshold optimization。这说明它值得学习和做 adapter spike，但也说明
它不是架构跃迁。它不负责 OpenAI-compatible 入口、LiteLLM 接入、runtime home、
日志、巡检和本地学习闭环，所以即使采用，也只能替换路由评分内核，不能替换
IntentMux 产品壳层。

## 证据

### 官方能力

Aurelio 的架构文档把系统拆成三类核心组件：

- encoder：把输入转成向量，支持 dense、sparse、multimodal；
- route：用 `name`、`utterances`、`score_threshold` 描述可匹配意图；
- index：存储并检索 route vectors，包含 `LocalIndex`、`HybridLocalIndex`、
  Pinecone、Qdrant、Postgres 等实现。

官方 threshold optimization 文档明确支持：

- `evaluate(X, y)`：用标注样本评估 route layer；
- `fit(X, y)`：为每个 `Route` 拟合 threshold；
- `get_thresholds()`：读取优化后的 per-route threshold。

官方 index 文档还说明：

- `LocalIndex` 是内存索引，适合开发、测试和小规模 route；
- 远程 index 用于持久化和更大规模；
- `LocalIndex.add()` 支持 `metadata_list`；
- `LocalIndex.get_utterances(include_metadata=True)` 可读回 utterance 和 metadata。

参考：

- https://docs.aurelio.ai/semantic-router/user-guide/concepts/architecture
- https://docs.aurelio.ai/semantic-router/user-guide/features/threshold-optimization
- https://docs.aurelio.ai/semantic-router/user-guide/components/indexes
- https://docs.aurelio.ai/semantic-router/client-reference/index/local

### 本机临时验证

只使用临时 `uv --with semantic-router` 验证导入，没有修改 `pyproject.toml` 或
`uv.lock`。

验证命令证明这些对象可导入：

```text
semantic_router_import=ok
semantic_router.route.Route
semantic_router.routers.semantic.SemanticRouter
semantic_router.index.local.LocalIndex
semantic_router.encoders.huggingface.HuggingFaceEncoder
```

验证 `Route` 可以承载中文 utterances：

```text
Route(name="lite", utterances=["解释一下这个命令是什么意思", "翻译成中文"])
```

临时安装拉入约 63 个包，并在导入时触发 LiteLLM 远程价格表请求失败后的本地
回退 warning。这说明它不是“零成本小函数依赖”，不能直接进入默认主线依赖。

## IntentMux 映射

| IntentMux 概念 | Aurelio 映射 | 备注 |
| --- | --- | --- |
| `lite` / `deep` | 两个 `Route.name` | 产品仍只保留两档 |
| route bank examples | `Route.utterances` | 可由当前 YAML 生成 |
| request embedding | encoder(query) | encoder 选择需由 IntentMux 配置治理 |
| route-bank vector cache | index | `LocalIndex` 可做内存基线，持久化另行评估 |
| threshold / margin | `score_threshold` / fitted thresholds | margin 可能仍需 IntentMux 外层保留 |
| match provenance | index metadata 或 IntentMux wrapper | 必须保留 `match_source` / `match_index` / `match_text_sha256` |
| quality calibration | `evaluate` / `fit` | 需要真实 eval/calibration set，不能只用玩具样本 |

## Adapter Gate

进入主线前必须补一个独立 branch/spike，通过以下门槛：

1. **不污染主线依赖**：先以 optional dependency 或 spike 分支验证，不直接改默认安装。
2. **本地 encoder 优先**：证明可以使用本地或 OpenAI-compatible embedding endpoint。
   如果只能用官方 OpenAI encoder 或 HuggingFace endpoint，不能作为默认路径。
3. **可审计输出**：单条请求必须能记录 route、score、threshold、候选 match、
   route source、example hash。
4. **持久化策略明确**：不能每次请求重新 embedding 全量 route bank；route bank
   变更才重建 index/cache。
5. **中英文样本可跑**：同一批 bilingual eval/calibration 样本能比较
   current-router 与 Aurelio adapter。
6. **低侵入接入**：IntentMux 的 OpenAI-compatible API、LiteLLM sidecar、
   日志、健康检查不被替换。

## 风险

- Aurelio 是 Python library，不是完整网关；采用后仍要维护 IntentMux 外壳。
- 本机临时导入已显示依赖面不小，并会加载 LiteLLM 相关逻辑。
- 文档证明支持 threshold fitting，但不等于它天然适配 IntentMux 的
  `lite` / `deep` 成本语义。
- route choice 示例里 `similarity_score` 可能为空；审计字段是否足够需要
  本机 adapter demo 进一步验证。
- OpenAI-compatible embedding endpoint 适配能力未验证；可能需要自定义 encoder。

## 交叉验证状态

本轮 Retinue 只读交叉验证没有形成可信产物：

- Aurelio 子任务被 Retinue 标记为 `read_only_write_intent`，输出不能作为采信证据；
- vLLM 子任务被 Retinue 标记为 `provider_blank_assistant`，没有有效内容。

因此本文只采用官方文档、本机临时导入验证和仓库现状作为证据。

## 当前建议

短期不 fork、不进默认依赖。先采纳它的 route/threshold/evaluate 方法作为设计
参考；下一步如果继续验证，只做一个最小 adapter spike：

```text
examples route/eval yaml
  -> build Aurelio routes
  -> build/reuse local index
  -> run bilingual eval
  -> export IntentMux-style audit JSON
  -> compare current-router baseline
```

如果这个 spike 不能提供可审计 match provenance，Aurelio 只能作为 threshold
optimization 和 route/index API 的参考，不能替换当前内核。
