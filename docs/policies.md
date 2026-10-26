# Policies & safety

Policies are enforced by `ToolExecutor` in code. Prompts can *ask* a model to behave, but only the
executor decides whether a tool runs.

## Evaluation order

1. **Registry**: an unknown tool is denied.
2. **Arguments**: strict Pydantic validation (no extra fields, no coercion). Failures become
   `invalid_args` outcomes and the tool is not called.
3. **Repeated-failure guard**: an identical call that already failed `repeated_failure_limit` times is
   blocked.
4. **Tool budget**: `max_tool_calls` per run.
5. **Allowlist**: the tool must match the agent's `tools` globs.
6. **Rules**: enabled rules sorted by ascending `priority`. The first rule whose `tools`, `roles`,
   `agents` globs and **all** `conditions` match decides the effect. Rules with `max_calls_per_run`
   match only once the limit is reached (rate limiting).
7. **Default**: `default_effect` (allow unless configured otherwise).

Effects: `allow`, `deny` (the step is `blocked` and the model sees the reason), `require_approval` (the run
pauses in `WAITING_APPROVAL`, an `approvals` row is created and the run resumes from its checkpoint when
a human decides).

## Conditions

`eq, ne, lt, lte, gt, gte, in, not_in, regex, exists, path_prefix, not_path_prefix`. Arguments
can be addressed with dotted paths (`customer.id`). Path operators normalise `..` and `\`, so
`/srv/data/../../etc/shadow` is **not** under `/srv/data`. Incomparable types never match.

## Policy as code

```yaml
rules:
  - name: block-large-refunds
    description: Refunds above $500 are never issued by an agent.
    effect: deny
    tools: ["refund.issue"]
    conditions: [{arg: amount, op: gt, value: 500}]
    priority: 10
  - name: one-refund-per-run
    effect: deny
    tools: ["refund.issue"]
    max_calls_per_run: 1
    priority: 15
  - name: approve-refunds-over-100
    effect: require_approval
    tools: ["refund.issue"]
    conditions: [{arg: amount, op: gt, value: 100}]
    priority: 20
```

`PUT /api/v1/policies/yaml` validates and replaces all rules atomically.
`POST /api/v1/policies/simulate` evaluates a hypothetical call exactly as the runtime would.

## Other protections

- **Tenant isolation**: project-scoped repositories. Cross-project access returns 404.
- **Authentication**: hashed API keys (`X-API-Key` or `Authorization: Bearer`).
- **Redaction**: sensitive keys (`password`, `token`, `api_key`, …), key/token patterns, private
  keys, card numbers and `key=value` pairs in free text are masked in the event log and in tool I/O
  shown to the model.
- **Budgets**: steps, tokens, wall-clock time and tool calls, each enforced with a recorded
  `budget.exceeded` event.

The security test suite (`tests/security`) asserts each of these properties.
