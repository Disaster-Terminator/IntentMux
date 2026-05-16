# Agent Framework Integration

Agent frameworks are higher risk than ordinary chat clients. They often run
long contexts, tool calls, code edits, shell commands, and review loops. A weak
model can fail in ways that are harder to detect than a normal answer-quality
drop.

## Recommended Entry Policy

Use `model=auto` for ordinary mixed traffic when fallback to the configured
fallback route, normally `lite`, is acceptable. Existing LiteLLM sidecar clients
may keep using the legacy `model=semantic-router` entry; it has the same
automatic-routing semantics but is no longer the canonical advertised model.

| Requested model | Meaning | Agent behavior |
| --- | --- | --- |
| `auto` | Preferred routed entry | Let IntentMux decide from request structure, hard rules, and semantic score |
| `semantic-router` | Legacy LiteLLM sidecar entry | Same as `auto`; keep only for compatibility |
| `lite` | Explicit lightweight tier | Use for known low-risk utility calls |
| `deep` | Explicit high-capability tier | Use for code, tools, review, incidents, and security-sensitive work |

Use an explicit model entry when the caller already knows the workload needs a
specific tier:

```json
{
  "model": "deep",
  "messages": [
    {"role": "user", "content": "Review this patch and run the required checks."}
  ]
}
```

`model=lite` and `model=deep` are explicit route overrides. `metadata.route_id`
remains supported for clients that keep sending `model=auto` or legacy
`model=semantic-router`:

```json
{
  "model": "auto",
  "metadata": {
    "route_id": "deep"
  },
  "messages": [
    {"role": "user", "content": "Review this patch and run the required checks."}
  ]
}
```

`metadata.route_id` is checked before hard rules and semantic similarity. Valid
route ids are product-level ids such as `lite` and `deep`, not deployment model
group names such as `your-lite-model` or `your-deep-model`. Legacy `fast` and `strong`
route ids are aliases for `lite` and `deep`.

`/v1/models` advertises only canonical entries: `auto`, `lite`, and `deep`.
It does not list `semantic-router`, `fast`, `strong`, or upstream model group
names.

## Agent Structure Signals

IntentMux records safe structural signals from OpenAI-compatible requests in
route audit logs. These signals include message counts, approximate input
character count, whether `tools` / legacy `functions` are present, whether
there is tool-call history, whether `response_format` is set, and whether the
request contains multimodal content.

The router also consumes the strongest generic agent signals before semantic
embedding fallback. Requests with `tools`, legacy `functions`, tool-call
history, `tool_choice`, or long multi-turn context are routed to `deep` with
`policy_id=agent_signal` by default. This is deliberately structural: it does
not hardcode OpenCode, Hermes, Retinue, or any other local framework name.

These fields do not store prompt text, tool schemas, tool outputs, file
contents, or framework names in the route audit log. Raw prompt review logs, if
enabled for local debugging, should stay in a private runtime volume and should
not be committed.

## When To Force `deep`

Force `deep` for:

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
- calls where falling back to `lite` is an intentional cost-saving behavior.

## Why This Matters

IntentMux intentionally falls back to `fallback_route_id` when embedding scores
are low-confidence or embeddings are degraded. That is the right default for a
lightweight local gateway, but agent workloads often prefer predictable quality
over cost savings. Explicit model entries or route ids give agent frameworks a
deterministic escape hatch without changing LiteLLM provider routing, provider
keys, budgets, or fallback.

## Validation

Before making an agent framework use `auto` or legacy `semantic-router` by default:

1. Run the LiteLLM-entry E2E script.
2. Run a representative tool-call or code-review prompt.
3. Check the route log for `route_id`, `target_model`, `reason`, and
   `request_id`.
4. Check `format_signals` for `tools_present`, `tool_history`, `message_count`,
   and `approx_input_chars`.
5. If agent prompts are still mostly `low_confidence`, check whether the client
   strips `tools`, tool history, or `tool_choice`; then either preserve those
   request fields or configure the framework to send `model=deep` or
   `metadata.route_id=deep` for that agent class.
