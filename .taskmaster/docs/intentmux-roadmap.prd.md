# IntentMux 路线图 PRD

## 问题背景

IntentMux 已经不是一个简单 sidecar 原型。当前项目已经具备：

- OpenAI-compatible `auto` / `lite` / `deep` 路由入口；
- LiteLLM-first sidecar 接入；
- 可审计 route audit log 和可选本地 prompt review log；
- health / ready / daily health / review candidates；
- route quality report 和 baseline 对比；
- 语义资产构建、route/eval/calibration 拆分；
- Apache-2.0 开源仓库元数据。

新的主要问题不是“缺一个想法”，而是项目治理复杂度已经超过单个对话上下文：

- 文档、计划、日志、生产约束、调研结论和 review 意见太分散；
- 语义路由质量不能靠猜，需要数据、日志、eval 和 before/after 报告；
- 本地自用资产和 public repo 边界必须稳定，不能把本机路径、raw prompt、密钥或运行时配置混入仓库；
- 需要一个可解析、可排序、可依赖管理的任务系统，帮助 agent 持续推进，而不是不断扩写 markdown 计划。

Task Master 在本项目中的定位是“任务数据库和依赖规划层”，不是替代 Codex/Retinue/Superpowers 执行代码。

## 产品愿景

IntentMux 是轻量 OpenAI-compatible `lite` / `deep` 两档语义路由器。

核心定位：

- **中文优先，不只支持中文**：中文路由质量是差异化；英文数据和成熟英文路由方法用于避免默认能力落后。
- **轻量，本地，自用友好**：不引入大型调度平台，不把 provider routing、key、budget、fallback 从 LiteLLM 抢过来。
- **成本优先，证据升级**：默认走 `lite`，只有明确证据表明需要高能力或高风险处理时升级到 `deep`。
- **可学习，但不自我修改**：运行时不自动改阈值、hard rule 或 route bank；学习发生在离线日志、AI review packet、人审和导入门禁里。
- **证据驱动，不做大型标注/训练项目**：可学习不等于启动大规模人工标注、训练 router model 或让 AI 自造语料。

标准决策链：

```text
显式 route
  -> 高精度 hard escalation
  -> route-bank embedding 相似度
  -> threshold + margin
  -> 低置信 fallback 到 lite
```

## 目标用户

1. **本地生产使用者**
   - 已经运行 LiteLLM；
   - 希望用很小接入成本，把请求按复杂度分到不同模型组；
   - 需要日志可读、可审计、可回放；
   - 不希望路由服务接管 provider key、budget、fallback。

2. **未来 clean-clone 用户**
   - 想快速启动一个轻量语义路由器；
   - 需要清晰知道配置入口、运行时目录、模型映射、日志目录；
   - 不应该看到 RayStorm 本机路径或本地部署假设。

3. **AI coding agent**
   - 需要稳定的项目控制面；
   - 需要知道哪些计划是当前有效、哪些是归档；
   - 需要按依赖关系推进，而不是靠单轮上下文记忆。

## 成功标准

- 新 agent 先读 `.taskmaster/` 和 `docs/PROJECT_CONTROL.md`，就能理解下一步任务。
- 每个重要路由质量改动都能追到任务、测试策略和 before/after 证据。
- public repo 只包含通用配置、示例、PRD、任务元数据和文档；本地 runtime 资产、日志、prompt、密钥保持 ignored。
- Task Master 能生成一个按依赖排序的任务库，覆盖数据管线、eval、cache、学习导入门禁、生产 rollout。
- 当前中文 PRD 是用户可审计入口；英文内容只作为机器/外部工具辅助，不作为唯一权威。

## 范围内

### 1. 默认语义数据基线

权威公开数据集应尽量全量进入本地 ignored normalized records；在线 route/eval/calibration 产物按 `limit` 限量。

要求：

- `config/route_sources.yaml` 是 source manifest；
- 默认保留 `zh-CN` 和英文；
- 默认排除 `zh-TW`，除非用户显式启用；
- MASSIVE 等有官方 split 的数据集按 split 接入：
  - train 作为 route 候选；
  - dev 作为 eval 候选；
  - test 作为 calibration 候选；
- 保留 `source`、`license`、`language`、`slice`、`proposed_use`、`route_id`；
- 少量公开脱敏的简体中文 `deep` 样本只能作为 seed/overlay，不是长期替代权威数据集的手工流程。

### 2. 路由质量评估

路由质量必须通过 baseline、slice 和 deep-call rate 判断。
所有 route policy 改动都必须同时看质量收益和成本影响；`deep` 调用率是质量报告的一等指标，不是事后备注。

要求：

- 对比 `current-router`、`always-lite`、`always-deep`、`hard-rule-only`；
- 按 language、slice、route id、source、decision policy 输出指标；
- route-bank recall smoke 只能证明样本加载可达，不能证明泛化质量；
- 历史日志含 legacy `fast` / `strong` 时，策略判断优先看当前日或迁移后的日志。

### 3. 日志驱动学习导入门禁

IntentMux 应该越用越聪明，但不能把 AI 判断直接当真。

要求：

- 从 audit log 和可选本地 prompt review log 生成 review candidates；
- 生成 AI review packet，但脚本本身不调用 AI provider；
- AI 输出必须经过 schema 校验和摘要；
- 只有接受、脱敏、route id 合法、隐私安全的样本才能进入 regression/eval/route-bank 资产；
- 人类只审 policy、privacy、不确定或高风险样本。

### 4. Embedding 缓存

运行时保持轻量，但不要每次重启都重复嵌入 route bank。

要求：

- 只缓存 route-bank utterance embedding，不缓存用户请求 embedding；
- 第一版使用 JSONL + manifest；
- manifest key 包含 route-bank hash、embedding model、vector dim、builder version；
- 当前阶段不实现 SQLite / FAISS / Chroma / Qdrant / pgvector；只有 JSONL cache 被允许进入近期任务。
- 向量数据库属于后续重新立项事项，不能由 Task Master 根据本 PRD 自动展开实现任务。

### 5. 生产安全部署

仓库改动和本地生产 rollout 必须分离。

要求：

- `routes.yaml` 是唯一 route-policy / target_model 映射入口；
- runtime config、logs、semantic sets、prompt review logs、本机路径不进入 public repo；
- 本机生产推荐 LiteLLM-first sidecar；
- 任何生产 rollout 前必须跑 tests、route contract、preflight、ready、smoke decision；
- 不改变生产阈值、hard rule 或模型映射，除非有 before/after 证据。

## 范围外

- 训练 router model；
- 默认引入 vector database；
- 大规模人工标注；
- 自生成语义语料冒充真实质量证据；
- bulk translate 英文 benchmark 并声称是中文质量证据；
- 把 AI label 当 ground truth；
- 运行时自动修改阈值、hard rule 或 route bank；
- 把 LiteLLM 的 provider routing、key、budget、fallback 挪进 IntentMux。

## 仓库结构映射

- `router/`：运行时网关、路由决策、配置读取、审计日志、ready。
- `scripts/build_semantic_assets.py`：normalized semantic records 和 route/eval/calibration 生成。
- `scripts/build_route_bank.py`：source loader 和 legacy route-bank builder。
- `scripts/eval_routes.py`：路由 eval。
- `scripts/generate_route_quality_report.py`：质量报告。
- `scripts/select_review_candidates.py`：从日志选择复核候选。
- `scripts/prepare_ai_review_packet.py`：生成 AI 可读复核包。
- `scripts/summarize_ai_review.py`：校验和汇总 AI 输出。
- `config/routes.yaml`：开发默认 route policy。
- `config/route_sources.yaml`：公共数据源 manifest。
- `examples/intentmux-home/`：运行时目录模板。
- `docs/PROJECT_CONTROL.md`：人类可读项目控制面。
- `.taskmaster/`：任务数据库、PRD、复杂度报告和任务拆分。

## 已知缺口到任务主题的映射

| 已知缺口 | 对应任务主题 | 验收方向 |
| --- | --- | --- |
| route bank 已从 bootstrap-v1 进化为数据管线，但还不是正式质量基线 | 默认语义数据基线、路由质量评估 | 能输出 source/language/slice/use 计数和 before/after 报告 |
| accepted findings 尚未稳定导入 redacted regression cases | 日志驱动学习导入门禁 | 有 schema、隐私校验、导入命令和回滚策略 |
| route/eval/calibration 已拆分，需要持续防止交叉污染 | 默认语义数据基线 | 测试证明 split 不互相污染 |
| embedding vectors 尚未跨重启持久化 | Embedding 缓存 | JSONL cache + manifest invalidation 可用 |
| threshold 和 margin 还未由代表性证据校准 | 路由质量评估 | 报告含 baseline、slice、deep-call rate 和建议 |
| 历史日志含 legacy route 名称 | 路由质量评估、生产安全部署 | 当前策略判断优先使用 current-day 或 post-migration 日志 |

## Task Master 原子任务要求

Task Master 解析本 PRD 时，每个生成任务应尽量包含：

- `description`：用中文描述目标；
- `dependencies`：列出必须先完成的任务；
- `acceptance criteria`：用可检查条件描述完成标准；
- `test strategy`：说明需要跑哪些测试、脚本或日志检查；
- `repo boundary`：说明是否只改 public repo，是否涉及本地 runtime；
- `stop condition`：触碰生产、raw prompt、密钥、阈值或 vector DB 时必须暂停讨论。

## 初始任务主题

Task Master 应从这份 PRD 拆出可执行任务，至少覆盖：

1. 对齐 `.taskmaster/` 和 `docs/PROJECT_CONTROL.md`，明确谁是任务控制面、谁是人类控制面。
2. 将默认语义数据基线变成可重复数据管线，输出 source/language/slice/use 计数。
3. 强化 route quality report，让它能说明某个路由改动为什么安全或不安全。
4. 设计并实现 JSONL embedding cache 的第一版边界。
5. 设计学习导入门禁：AI-reviewed candidates -> redacted regression/eval/route-bank assets。
6. 补生产 rollout checklist，确保 repo 改动不等于本地 runtime 改动。
7. 精简和归档旧计划文档，降低 agent 和人类审计成本。
8. 明确中文优先、英文不掉队的数据策略，避免过拟合本机 Retinue/OpenCode 日志。

## 约束

- 不提交生成的 semantic sets、runtime logs、raw prompts、本地 `INTENTMUX_HOME`、`.env` 或 RayStorm 本机路径。
- 不在没有 before/after quality report 的情况下修改生产 threshold、margin、hard rule。
- 不在未验证 JSONL cache 极限前引入 SQLite 或 vector DB。
- 不把 Task Master 生成任务当成真实代码证据；代码、测试、日志和运行状态仍需实查。
- 不让 Task Master 替代 `docs/PROJECT_CONTROL.md`；后者仍是人类快速审计入口。

## 测试策略

- source manifest 解析、normalized records、split separation、cache invalidation 的单测；
- semantic asset builder 和 quality report 的 CLI 测试；
- `auto` / `lite` / `deep` / `semantic-router` 的 route contract；
- 生产 rollout dry run；
- daily health 和 review candidates 作为 dogfood 证据；
- 每次重要任务完成后更新 Task Master 状态，并在 commit 中保持可追踪。
