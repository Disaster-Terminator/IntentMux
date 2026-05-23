# Agent 框架接入

面向人的完整说明在 README；此文件只保留 agent/运维可执行规则。

## 入口

| model | 含义 |
| --- | --- |
| `intentmux` | 推荐自动路由入口 |
| | `lite` | 显式低成本/轻量路由 |
| `deep` | 显式高能力/高风险路由 |

`metadata.route_id` 也可显式指定 `lite` / `deep`。不要使用部署侧 target model
名作为 route id。

## 策略

- 普通混合流量用 `intentmux`。
- 调用方明确知道高风险时用 `deep`：生产事故、安全/权限/凭据、代码审查、复杂 debug。
- 低风险工具调用、解释、翻译、总结、格式转换可以用 `intentmux` 或 `lite`。
- `tools`、tool history、长上下文等结构信号只作为审计信号，不单独强制 `deep`。
- 如果日志显示某类 agent 请求长期低置信或误路由，再决定是否让该框架显式发 `deep`。

## 验证

接入或改默认模型前至少验证：

```bash
uv run python scripts/e2e_litellm_entry.py --litellm-base-url http://127.0.0.1:4000
uv run python scripts/router_log_summary.py /data/logs/routes/*.jsonl
```

检查 route log 中的 `route_id`、`target_model`、`reason`、`request_id`、
`format_signals`。不要从普通 audit log 解析 prompt。
