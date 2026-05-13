# Agent Framework Integration

Agent frameworks are higher risk than ordinary chat clients. They often run
long contexts, tool calls, code edits, shell commands, and review loops. A weak
model can fail in ways that are harder to detect than a normal answer-quality
drop.

## Recommended Entry Policy

Use `model=semantic-router` for ordinary mixed traffic when fallback to `fast`
is acceptable.

Use an explicit route override when the caller already knows the workload needs
the stronger tier:

```json
{
  "model": "semantic-router",
  "metadata": {
    "route_id": "strong"
  },
  "messages": [
    {"role": "user", "content": "Review this patch and run the required checks."}
  ]
}
```

`metadata.route_id` is checked before hard rules and semantic similarity. Valid
route ids are product-level ids such as `fast` and `strong`, not deployment model
group names such as `cheap-router` or `pro-router`.

## When To Force `strong`

Force `strong` for:

- coding agents that can edit files;
- agents that can run shell commands;
- code review and patch review;
- production incident analysis;
- security, credential, permission, or data-loss triage;
- long-running tool-call loops where a failed step is expensive to unwind.

Let semantic routing decide for:

- normal chat;
- translation, explanation, rewriting, and summarization;
- low-risk one-shot utility prompts;
- calls where falling back to `fast` is an intentional cost-saving behavior.

## Why This Matters

IntentMux intentionally falls back to `fallback_route_id` when embedding scores
are low-confidence or embeddings are degraded. That is the right default for a
lightweight local sidecar, but agent workloads often prefer predictable quality
over cost savings. Explicit route ids give agent frameworks a deterministic
escape hatch without changing LiteLLM provider routing.

## Validation

Before making an agent framework use `semantic-router` by default:

1. Run the LiteLLM-entry E2E script.
2. Run a representative tool-call or code-review prompt.
3. Check the route log for `route_id`, `target_model`, `reason`, and
   `request_id`.
4. If agent prompts are mostly `low_confidence`, configure the framework to send
   `metadata.route_id=strong` for that agent class.

