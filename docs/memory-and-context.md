# Memory & context engineering

## Memory model

| Field | Meaning |
|---|---|
| `kind` | `fact`, `episode` (what happened), `decision`, `strategy` (reusable lesson) |
| `subject_key` | What the memory is *about*; enables versioning and conflict detection |
| `scope` | `project`, `agent:<name>`, `user:<id>` or `run:<id>`; agents see only their `memory_scopes` (`agent:*` globs allowed) |
| provenance | `source_type`, `source_ref`, `created_by`, `run_id` |
| `trust`, `importance` | `0..1`; used for ranking and conflict resolution |
| `valid_from`, `expires_at` | Validity window; expired memories are excluded and lazily marked `expired` |
| `status` | `active`, `superseded`, `retracted` (with reason), `expired` |
| `lineage_id`, `version`, `supersedes_id` | Full version history |

### Lifecycle rules

1. Writing a memory whose `subject_key` already has an active memory **in the same scope** creates the
   next version and supersedes the old one. Writing identical content is a no-op.
2. `update()` always creates a new version. Moving a memory into another scope also supersedes the
   active memory on the same subject in the target scope.
3. `retract()` keeps the row for audit purposes. Retracted memories never enter context again.
4. Active memories that disagree about the same subject across scopes are reported by `conflicts()`,
   with a suggested winner (higher trust, then newer `valid_from`).

### Explaining an edit before applying it

`POST /api/v1/memories/{id}/impact` with `{"change": {…MemoryUpdate…}}` is a dry run of `update()`. It
reports the field changes, which agents gain or lose visibility, which memories the new version would
supersede, and, for each run that retrieved the memory (up to six), how that run's context would change:
memories that would enter it and memories that would leave it, with the reason. The context engine runs
on rewritten candidate rows (`assemble(simulate=…)`), using each run's recorded query and pinned items,
so nothing is written or recorded as a retrieval.

## Context assembly

```
query (task + input + last observation)
  │
  ├─ candidates   top-k by vector similarity (pgvector `<=>` or cosine scan), any status
  ├─ relevance    0.65·cosine + 0.35·keyword overlap
  ├─ hard filters retracted · superseded · expired · scope_mismatch · low_relevance
  ├─ conflicts    one winner per subject_key (trust, then recency) → conflict_lost
  ├─ score        w_rel·relevance + w_rec·recency(half-life) + w_imp·importance + w_trust·trust
  └─ packing      pinned task first, then by score while it fits the budget → budget
```

Every assembly produces a **ContextReceipt**:

```json
{
  "step": 3, "strategy": "ranked", "budget_tokens": 900, "used_tokens": 214,
  "included": [{"item_id": "mem_…", "subject_key": "refund_policy", "score": {"relevance": 0.71, "trust": 0.6, "total": 0.67}, "source": "import:docs/policy-handbook-v1.pdf (v1, active)"}],
  "excluded": [{"item_id": "mem_…", "subject_key": "refund_policy", "reason": "scope_mismatch",
                "detail": "scope 'agent:billing' not in ['project', 'agent:support']"}]
}
```

Receipts are stored as `context.assembled` events. Each considered memory also writes a
`memory_retrievals` row, which feeds the *retrieval history* in Memory Explorer: which runs used the
memory, which runs excluded it, and why.

`strategy="naive"` reproduces the common "stuff memories in insertion order" approach. It exists so
benchmarks can quantify what ranked assembly buys you.

`POST /api/v1/context/preview` (Memory Explorer → *What would the agent see?*) runs the same pipeline
as a dry run.
