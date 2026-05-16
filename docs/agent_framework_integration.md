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

The router records generic agent-like structure before semantic embedding, but
these fields are audit signals rather than hard route decisions. Requests with
`tools`, legacy `functions`, tool-call history, `tool_choice`, or long
multi-turn context are not routed to `deep` solely because of that structure.
IntentMux stays cost-first: explicit route overrides, high-precision hard
rules, semantic similarity, thresholds, and fallback decide the final tier.

These fields do not store prompt text, tool schemas, tool outputs, file
contents, or framework names in the route audit log. Raw prompt review logs, if
enabled for local debugging, should stay in a private runtime volume and should
not be committed.

## When To Force `deep`

Force `deep` for:

- production incident analysis;
- security, credential, permission, or data-loss triage;
- code review, patch review, or shell execution only when the request itself
  carries high-risk or high-complexity evidence.

Let semantic routing decide for:

- normal chat;
- translation, explanation, rewriting, and summarization;
- low-risk one-shot utility prompts;
- low-risk tool calls and read-only agent reviews where falling back to `lite`
  is an intentional cost-saving behavior.

## Why This Matters

IntentMux intentionally falls back to `fallback_route_id` when embedding scores
are low-confidence or embeddings are degraded. That is the right default for a
lightweight local gateway, including deployments where most traffic comes from
agent frameworks. Agent callers that know a request needs the stronger tier can
still use explicit model entries or route ids without changing LiteLLM provider
routing, provider keys, budgets, or fallback.

## Validation

Before making an agent framework use `auto` or legacy `semantic-router` by default:

1. Run the LiteLLM-entry E2E script.
2. Run a representative tool-call or code-review prompt.
3. Check the route log for `route_id`, `target_model`, `reason`, and
   `request_id`.
4. Check `format_signals` for `tools_present`, `tool_history`, `message_count`,
   and `approx_input_chars`.
5. If agent prompts are mostly `low_confidence`, review representative prompts
   before changing routes. Preserve `format_signals` for audit, but configure
   the framework to send `model=deep` or `metadata.route_id=deep` only for
   agent classes whose requests consistently need the stronger tier.
