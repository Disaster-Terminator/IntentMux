# 中文语义路由层 —— 接力文档

> 更新时间：2026-05-03 20:00 UTC+8
> 状态：方案已定，待编码落地
> 接力目标：实现轻量中文路由 sidecar，替换 LiteLLM 内置 complexity_router

---

## 1. 背景与问题

LiteLLM 内置的 `auto_router/complexity_router` 基于英文关键词规则打分，在中文环境下系统性低估复杂度：
- 代码关键词（"function", "class"）、推理标记（"step by step"）中文几乎匹配不到
- 结果：中文技术请求被分到 `SIMPLE` 档，打到 `cheap-router`，实际应该用 `pro-router`

当前 `smart-router` 仍挂在 `complexity_router` 上，配置注释已写明"初测仍建议手动指定"。

**目标**：把 `smart-router` 从 LiteLLM 内置路由迁到外部中文语义路由 sidecar，前置在 LiteLLM 前面。

---

## 2. 已评估方案（及排除理由）

| 方案 | 结论 | 理由 |
|------|------|------|
| aurelio-labs/semantic-router | ❌ 不推荐 | 126KB 本体轻量，但顶层 `__init__.py` 无条件 import `aurelio_sdk` + `litellm` SDK，即使只用 `OpenAIEncoder` 也必须全装。litellm Python SDK（>=1.61.3）会和 Docker 网关冗余，性价比低 |
| vllm-project/semantic-router | ❌ 排除 | K8s/Envoy 基础设施级，Rust + ModernBERT（英文分类器），面向云厂商集群调度。WSL 本地环境过度设计 |
| Arch-Router-1.5B | ❌ 排除 | language 标 en，底座虽 Qwen2.5 但中文 eval 未验证 |
| RouteLLM | ❌ 排除 | 研究型 strong/weak routing，不是中文意图分类器 |
| Not Diamond / Martian | ❌ 排除 | 商业服务，中国区/中文 eval 不明 |
| **手写轻量路由** | ✅ **推荐** | 30 行核心逻辑，零额外依赖，复用现有 LM Studio embedding，中文 utterance 完全可控 |

---

## 3. 推荐架构

```text
client / Hermes / OpenCode / OMO
        ↓
    [中文路由 sidecar]  ← 这是本次要写的
        - 收 /v1/chat/completions
        - 抽 latest user message
        - 调 LM Studio :1234 embedding（OpenAI-compatible）
        - cosine 相似度匹配 → 决定 route
        - 改写 model 字段为 cheap-router / pro-router / free-probe-router
        ↓
    LiteLLM :4000
        - 执行现有 order / fallback / cooldown / 监控
        ↓
    真实模型池
```

**sidecar 定位**：只做"分类决策 + model 改写"，不替代 LiteLLM 的执行层。

---

## 4. 技术约束

### 4.1 Embedding 后端
- **地址**：`http://127.0.0.1:1234/v1/embeddings`
- **格式**：OpenAI-compatible（已验证）
- **模型**：`text-embedding-jina-embeddings-v5-text-small-retrieval@q8_0`
- **常驻**：LM Studio 本地常驻，不需要额外启动

### 4.2 Python 环境
- **管理器**：`uv`（不是 pip/conda）
- **已有依赖**：`numpy`, `openai`, `openai-whisper`
- **新增需求**：仅 `requests` 或 `httpx`（很可能已有）
- **不需要**：semantic-router, litellm SDK, aurelio-sdk, torch, transformers

### 4.3 LiteLLM 不重启
- sidecar 是独立进程，LiteLLM Docker 容器不动
- `smart-router` 在 LiteLLM config.yaml 里的定义可保留或移除，不影响 sidecar 独立运行

---

## 5. 路由规则

### 5.1 Route 定义（中文 utterance）

```python
ROUTE_UTTERANCES = {
    "coding":      [
        "写个函数", "怎么实现", "代码审查", "优化这段代码",
        "报错了", "debug", "接口集成", "后端实现",
        "写代码", "编程", "调试", "review 代码"
    ],
    "analysis":    [
        "分析", "对比", "架构设计", "多步推理",
        "方案权衡", "评估", "复杂分析", "tradeoff",
        "一步一步", "仔细思考", "深入分析"
    ],
    "probe":       [
        "测试模型", "对比模型", "benchmark", "评估",
        "哪个更好", "跑个基准", "probe", "对比效果"
    ],
    "chat":        [
        "你好", "谢谢", "什么意思", "解释一下",
        "总结", "简单说明", "聊天", "闲聊"
    ],
}
```

### 5.2 路由映射

| 命中 route | 转发到 LiteLLM model |
|-----------|---------------------|
| coding | `pro-router` |
| analysis | `pro-router` |
| probe | `free-probe-router` |
| chat | `cheap-router` |
| 未命中（相似度 < threshold）| `cheap-router`（保守兜底）|

### 5.3 阈值建议
- 初始 `threshold = 0.55`，根据实际效果调
- 可以支持 `threshold_per_route` 让 probe 更灵敏

---

## 6. 下一步任务（编码 TODO）

### 6.1 核心路由模块
- [ ] `semantic_router.py`：embedding 调用 + cosine 相似度 + route 决策
- [ ] `main.py`：FastAPI/Flask HTTP sidecar，收 `/v1/chat/completions`
- [ ] 启动时预计算 route centroids（避免每次请求重复 embed utterances）

### 6.2 配置与部署
- [ ] 配置项：LM Studio base_url、模型名、threshold、routes 定义
- [ ] uv run / systemd / tmux 等启动方式
- [ ] 监听端口建议：`0.0.0.0:4001`（LiteLLM :4000 旁边）

### 6.3 集成到 Hermes
- [ ] Hermes `config.yaml` 的 `model.base_url` 从 `:4000` 切到 `:4001`（sidecar）
- [ ] 或 sidecar 只处理 `model=smart-router` 请求，其他透传

### 6.4 测试验证
- [ ] 中文 coding 请求 → 确认打到 pro-router
- [ ] 中文闲聊 → 确认打到 cheap-router
- [ ] 探活请求 → 确认打到 free-probe-router
- [ ] 阈值边界 case 调优

---

## 7. 关键参考文件

| 文件 | 说明 |
|------|------|
| `~/gateway/litellm/config.yaml` | LiteLLM 当前配置，定义了 cheap-router / pro-router / free-probe-router |
| `~/gateway/litellm/HANDOFF.md` | LiteLLM 部署接力文档 |
| LiteLLM 环境变量 | API keys 留在 LiteLLM 挂载目录；sidecar 不读取、不提交、不复制 |
| `C:\Users\Disas\OneDrive\Desktop\meta.md` | 路由方案调研结论原文（用户桌面） |

---

## 8. 注意事项

1. **不要装 semantic-router 包**：依赖冗余（litellm SDK + aurelio-sdk），且仍需自写 HTTP 层。手写 30 行更干净。
2. **不要动 LiteLLM 容器**：sidecar 是独立进程，不需要重启网关。
3. **embedding API 已验证兼容**：`/v1/embeddings` 返回标准 OpenAI 格式，可直接 requests.post。
4. **中文 utterance 优先覆盖 coding / analysis**：这是当前 complexity_router 最大的盲区。
5. **阈值可调**：先跑起来再精调，不要一开始追求 perfect accuracy。
