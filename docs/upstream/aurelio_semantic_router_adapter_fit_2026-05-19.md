# Aurelio Semantic Router Adapter Fit

日期：2026-05-19

## 结论

Aurelio Semantic Router 适合作为 IntentMux 的默认成熟路由依赖。IntentMux
保留 OpenAI-compatible / LiteLLM-first 网关外壳、审计日志和本地学习闭环。

推荐判断：

```text
Aurelio Python package as default router dependency -> IntentMux gateway shell
```

实现形态已经收敛为直接依赖 Aurelio Python 包：

```text
IntentMux shell
  -> default Aurelio Semantic Router in-process adapter
  -> LiteLLM / OpenAI-compatible upstream
```

Aurelio 不是在线外部服务；它作为 Python library 在 IntentMux 请求路径内被调用。
RouteLLM 不进入请求路径，只作为 quality / deep_call_rate / threshold calibration
的评估方法来源。

默认 adapter 形态改为 `HybridRouter + HybridLocalIndex`，因为它更接近成熟
semantic router 的 dense+sparse 实践，同时仍能保持本地轻量：

- dense 信号继续复用 IntentMux 现有 OpenAI-compatible embedding endpoint；
- sparse 信号使用本地 lexical hash encoder，不加载额外模型、不调用外部服务；
- `aurelio_hybrid_alpha` 默认 `0.3`，必须大于 `0`，避免 HybridLocalIndex
  计算 dense cosine 时出现零向量分母；
- `basic` 只保留为 fallback/debug baseline。

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

1. **本地 encoder 优先**：证明可以使用本地或 OpenAI-compatible embedding endpoint。
   如果只能用官方 OpenAI encoder 或 HuggingFace endpoint，不能作为默认路径。
2. **可审计输出**：单条请求必须能记录 route、score、threshold、候选 match、
   route source、example hash。
3. **持久化策略明确**：不能每次请求重新 embedding 全量 route bank；route bank
   变更才重建 index/cache。
4. **中英文样本可跑**：同一批 bilingual eval/calibration 样本能比较
   current-router 与 Aurelio adapter。
5. **低侵入接入**：IntentMux 的 OpenAI-compatible API、LiteLLM sidecar、
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

当前主线默认提供 `ROUTER_ROUTE_KERNEL=aurelio` 和
`ROUTER_AURELIO_ROUTER=hybrid`；`basic` 只是 fallback/debug baseline。下一步
如果继续验证，只做一个最小质量对比 spike：

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
