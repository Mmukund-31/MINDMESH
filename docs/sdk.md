# SDK guide

```python
from mindmesh import MindMesh
mm = await MindMesh("sqlite:///mindmesh.db", project="my-app").init()
```

`MindMesh(database_url, project=…, embedder="hashing:384" | "ollama:nomic-embed-text" | Embedder,
default_policy_effect=PolicyEffect.ALLOW)`. The URL may also come from `MINDMESH_DATABASE_URL`.

## Tools

```python
@mm.tool(side_effect=True, timeout_s=10, description="Issue a refund")
async def refund_issue(order_id: str, amount: float, reason: str) -> dict: ...

@mm.tool("kb.search")
def search(query: str, k: int = 3, ctx: ToolContext = None) -> list[dict]:   # sync tools run in a thread
    ctx.memory  # MemoryStore, ctx.run_id, ctx.agent, ctx.step
```

Each signature becomes a strict Pydantic model: unknown fields, missing fields and type coercion
(`"5"` for `int`) are rejected before execution. Raise `TransientToolError` to request a bounded
retry. Any other exception is a permanent failure.

## Agents

```python
mm.agent(AgentSpec(
    name="support", role="support",
    system_prompt="…",
    tools=["crm.lookup", "orders.get", "refund.issue"],   # allowlist (globs allowed)
    model="ollama:qwen3:8b",
    memory_scopes=["project", "agent:support"],
    context=ContextConfig(budget_tokens=900, strategy="ranked", min_relevance=0.12),
    limits=Limits(max_steps=8, max_tool_calls=20, max_tokens=60_000, timeout_s=300,
                  tool_timeout_s=20, max_retries=2, repeated_failure_limit=2),
    enforce_policies=True,
    remember_outcomes=False,   # write an episode memory after each run
))
```

## Runs

| Call | Purpose |
|---|---|
| `await mm.run(agent, task, input, overrides=RunOverrides(...), wait=True)` | execute (or `wait=False` for background) |
| `await mm.resume(run_id)` | continue after an approval decision or recover an interrupted run |
| `await mm.cancel(run_id)` | cooperative cancellation (works across processes via `cancel_requested`) |
| `await mm.resolve_approval(approval_id, approve, resolver=, note=)` | decide + resume |
| `await mm.replay(run_id)` | safe replay with recorded outputs (no tools, no model) |
| `await mm.rerun(run_id, RunOverrides(...))` | re-execute live with the current memory/policies and overrides |
| `await mm.compare(a, b)` | step-aligned diff, divergence step, context deltas, metric deltas |

## Memory

```python
m = await mm.memory.add(MemoryCreate(content="…", subject_key="refund_policy", scope="project",
                                     kind="fact", trust=0.9, importance=0.8,
                                     provenance=Provenance(source_type="import", source_ref="handbook.pdf")))
await mm.memory.update(m.id, MemoryUpdate(scope="project", reason="applies to all agents"))  # new version
await mm.memory.retract(m.id, "superseded by legal", by="alice")
await mm.memory.search("refund window", k=5, scopes=["project"])
await mm.memory.conflicts(); await mm.memory.versions(m.id); await mm.memory.retrievals(m.id)
```

## Policies

```python
await mm.add_policy(PolicyRuleIn(name="no-big-refunds", effect="deny", tools=["refund.issue"],
                                 conditions=[Condition(arg="amount", op="gt", value=500)], priority=10))
await mm.load_policies(open("policies.yaml").read())   # policy as code, replaces all rules
```

## Workflows

```python
wid = await mm.run_workflow(WorkflowSpec(name="brief", goal="…", tasks=[
    WorkflowTaskSpec(key="research", agent="researcher", task="…"),
    WorkflowTaskSpec(key="write", agent="writer", task="…", depends_on=["research"], max_attempts=3),
    WorkflowTaskSpec(key="verify", agent="verifier", task="…", depends_on=["write"], verifies="write"),
]))
```

## Deterministic testing with scripted brains

```python
from mindmesh import brain

@brain("my-agent")
def decide(req):              # sees only req.context, req.history, req.task_input
    if not req.history:
        return {"type": "tool_call", "tool": "kb.search", "args": {"query": req.task}}
    return {"type": "final_answer", "answer": "…"}

AgentSpec(name="x", model="scripted:my-agent", ...)
```

Scripted brains run your agent through the real runtime (context, policies, retries, tracing), which
makes evaluation suites reproducible. Swap `model` for `ollama:…` to test a real model on the same suite.

## Custom providers

```python
from mindmesh.models import register_provider
register_provider("vllm", lambda model: MyVLLMProvider(model))   # AgentSpec(model="vllm:Qwen3-32B")
```
