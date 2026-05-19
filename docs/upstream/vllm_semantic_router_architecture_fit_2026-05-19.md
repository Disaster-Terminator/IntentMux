# vLLM Semantic Router Architecture Fit

日期：2026-05-19

## 结论

vLLM Semantic Router 现在应作为 **methodology-only / architecture reference**，
不应 fork，也不应作为 IntentMux 当前默认运行依赖。

推荐判断：

```text
methodology-only now
fork only if IntentMux intentionally becomes a heavier standalone gateway
```

原因是它的成熟度主要体现在系统级 signal-driven routing、provider/gateway
控制面、Envoy ExtProc、Kubernetes/operator、dashboard 和多 provider 编排。
这些能力比 IntentMux 当前本地轻量 sidecar 目标重很多，并且和 LiteLLM 已有的
provider routing、fallback、budget、key 管理存在明显重叠。

## 证据

### 官方能力

vLLM Semantic Router 自述为面向 mixture-of-models 的开源 LLM router，强调
rule、latency heuristic、reinforcement learning、ML selection 等多种 routing
strategy，并以 signal-driven decision routing 组合 cost、privacy、latency、
safety 等约束。

官方 signal 文档把 routing 拆成：

- `routing.signals`：命名 detector；
- `routing.projections`：跨 signal 的分区、score、mapping；
- `routing.decisions`：引用 signal/projection 输出做路由决策。

signal 类型还区分：

- heuristic signals：keyword、language、structure、context、authz 等；
- learned signals：complexity、domain、embedding、modality、fact-check、
  jailbreak、PII、preference、reask、kb、user-feedback 等。

官方 Envoy ExtProc 文档显示它可作为 in-path processor，读取请求 body，
设置 header 或 destination endpoint，再由 Envoy 路由到后端 model cluster。

参考：

- https://vllm-semantic-router.com/
- https://vllm-semantic-router.com/docs/tutorials/signal/overview/
- https://vllm-semantic-router.com/docs/overview/architecture/envoy-extproc/
- https://github.com/vllm-project/semantic-router

## IntentMux 映射

| IntentMux 概念 | vLLM Semantic Router 映射 | 当前判断 |
| --- | --- | --- |
| `auto` / `semantic-router` entry model | listener / gateway entry | 可参考，不照搬 |
| `lite` / `deep` | model aliases / model cards / decisions | 可参考命名和 policy 表达 |
| hard rules | heuristic signals | 应学习其 signal 命名和复用方式 |
| route-bank embedding | learned embedding signal | 可学习，不直接迁移 |
| threshold / margin | decision condition / projection band | 可学习其分层决策表达 |
| request format signals | structure / context / language signals | 可作为未来多信号输入 |
| audit logs | signal/projection/decision trace | 应学习其可解释输出 |
| LiteLLM provider routing | providers / model catalog | 与 LiteLLM 重叠，应避免重复建设 |

## 可复用思想

这些思想值得进入 IntentMux 的后续设计，但不是直接引入上游代码：

1. **Signal / Projection / Decision 分层**  
   先回答“检测到了什么”，再回答“这些信号如何组合”，最后回答“路由到哪里”。
   这比把关键词、embedding、agent heuristics、风险规则写成一坨 if/else 更可审计。

2. **按需计算 signal**  
   当前 IntentMux 应保持轻量：只计算当前 policy 用得到的信号，避免为了“成熟感”
   每个请求都跑复杂模型或全套检测。

3. **审计输出围绕决策链**  
   每条请求应能解释：哪些 signal 命中、分数是多少、threshold/margin 是多少、
   哪个 decision 赢了、最终 route alias 是什么。

4. **Provider 层不要重复造 LiteLLM**  
   IntentMux 在 LiteLLM-first 场景下只决定 `lite` / `deep`，不接管 provider
   fallback、budget、key 和模型池；standalone gateway 可以作为扩展形态，但不是
   当前主线优先级。

5. **配置可 review**  
   规则、语义样本、阈值和决策逻辑要能被人和 agent 审查，而不是只藏在代码里。

## 为什么不 fork

- 形态更接近完整 gateway/control-plane，而 IntentMux 当前目标是本地轻量路由器。
- Envoy ExtProc、Kubernetes/operator、provider catalog 等能力会把部署复杂度抬高。
- LiteLLM 已经承担 provider 路由和服务治理；fork 后会迫使 IntentMux 重新解释
  与 LiteLLM 的职责边界。
- 当前最缺的是 bilingual route quality、calibration、audit trace 和学习闭环，
  不是更重的控制面。

## 当前建议

短期采用方法论：

```text
current-router
  -> split internal evidence into signal-like records
  -> keep lite/deep decision as product-level output
  -> export audit trace with signal/projection/decision style fields
  -> compare quality by baseline/calibration reports
```

只有当 IntentMux 明确从 LiteLLM-first sidecar 转向完整 standalone gateway，并且
愿意承担 provider/control-plane 复杂度时，才重新评估 fork 或深度 adapter。

在此之前，vLLM Semantic Router 的价值是校准我们的抽象：不要只做
`cosine > threshold`，而要逐步把 route reason 变成可组合、可审计、可回归的
信号决策链。

## 交叉验证状态

本轮 Retinue 只读交叉验证被标记为 `provider_blank_assistant`，没有有效内容。
因此本文只采用官方文档和仓库现状作为证据。
