# 脱敏路由复核

此文件保留最小命令。完整质量闭环见 `docs/log_driven_quality_loop.md`。

生成候选：

```bash
uv run python scripts/select_review_candidates.py /data/logs/routes/*.jsonl \
  --routes /data/config/routes.yaml \
  --prompt-path "/data/logs/prompts/*.jsonl" \
  --json-output /tmp/intentmux-review-candidates.json \
  --markdown-output /tmp/intentmux-review-candidates.md
```

生成 AI 复核包：

```bash
uv run python scripts/prepare_ai_review_packet.py \
  --input /tmp/intentmux-review-candidates.json \
  --json-output /tmp/intentmux-ai-review-packet.json \
  --markdown-output /tmp/intentmux-ai-review-packet.md
```

汇总 AI 输出：

```bash
uv run python scripts/summarize_ai_review.py \
  --input /tmp/intentmux-ai-review-result.json \
  --json-output /tmp/intentmux-ai-review-summary.json \
  --markdown-output /tmp/intentmux-ai-review-summary.md
```

默认产物不包含 raw prompt。只有本地私有审查可显式使用 raw prompt review log。
