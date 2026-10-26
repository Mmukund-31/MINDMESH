# MINDMESH

**The reliability and control plane for AI agents.** MINDMESH helps developers build agents that
remember what matters, use context intelligently, act within enforced boundaries, collaborate
effectively, and improve through measured failures.

MINDMESH is not another chatbot or agent framework. It wraps *your* agents with:

| Capability | What you get |
|---|---|
| **Intelligent memory** | Facts, episodes, decisions and strategies with provenance, scope, versions, expiry, retraction and conflict detection |
| **Adaptive context engineering** | Hybrid retrieval → hard filters → conflict resolution → weighted scoring → token-budget packing, with a **context receipt** that explains every inclusion *and exclusion* |
| **Control & safety in code** | Tool allowlists, strict argument validation, priority-ordered policy rules (allow / deny / require approval), rate limits, budgets, timeouts and human approvals, all enforced **outside the LLM** |
| **Reliable runtime** | Explicit state machines, bounded retries with backoff, output repair, repeated-failure guard, checkpoints, resume and crash recovery, cooperative cancellation |
| **Tracing & replay** | Persistent append-only event log (span tree), safe replay from recorded outputs (no side effects), reruns with new configuration, and step-aligned run diffs |
| **Multi-agent orchestration** | DAG workflows with parallelism, handoffs, a shared evidence board, retries and verifier-driven re-work |
| **Evaluation** | Reproducible benchmark suites comparing a baseline agent stack with MINDMESH on success, retrieval quality, context efficiency, safety and recovery |
| **MINDMESH Studio** | A React dashboard with Overview, Execution Studio, Memory Explorer, Control Room, Orchestration Lab and Replay Lab, all on live backend data |

Everything runs locally: SQLite or PostgreSQL + pgvector, and Ollama with open-weight models (e.g. Qwen3).
No proprietary API is required.

---

## Quickstart (no Docker, fully offline)

Requires Python ≥ 3.12 and Node ≥ 20.19.

```bash
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[server,dev]"

mindmesh demo refund      # the signature demo in your terminal (fail → diagnose → fix → rerun → benchmark)
mindmesh demo seed        # seed demo data for Studio
mindmesh serve            # API on http://127.0.0.1:8000  (OpenAPI docs at /docs)

cd studio && npm install && npm run dev                 # Studio on http://localhost:5173
```

Studio uses the development API key `mm_dev_local_key_change_me` by default. Set `MINDMESH_API_KEY`
on the server, or create a key with `mindmesh create-key --project <name>`.

## Full stack with Docker Compose

```bash
docker compose up -d --build                         # Postgres+pgvector, API, Studio
docker compose run --rm server mindmesh demo seed    # optional demo data
open http://localhost:5173

# with a local open-weight model (downloads qwen3:8b + nomic-embed-text)
docker compose --profile llm up -d
MINDMESH_MODEL=ollama:qwen3:8b MINDMESH_EMBEDDER=ollama:nomic-embed-text docker compose --profile llm up -d server
```

## The signature demonstration

A support agent decides refund requests. The refund policy was updated (premium customers now have
30 days), but the billing agent stored the update in its **private scope**:

1. **Fail.** Premium customer C-1042 asks for a refund 21 days after delivery. The agent answers
   `DENIED: … outside the 14-day refund window`. A human flags the run as incorrect.
2. **Diagnose.** Execution Studio shows the trace. The **context receipt** for the decision step
   shows that the current policy was *excluded* with `scope_mismatch` (`scope 'agent:billing' not in
   ['project', 'agent:support']`), while the stale 14-day fact was included.
3. **Fix.** In Memory Explorer, promote the updated policy to `project` scope. MINDMESH creates
   version 2 and automatically supersedes the stale fact, keeping the full provenance.
4. **Replay & compare.** Rerun the same task: `APPROVED: refunded $79.00 …`. Replay Lab shows the
   runs diverged at step 1, with the context delta (`− refund window 14 days`, `+ premium customers
   within 30 days`). A *safe replay* of the original reproduces it exactly without re-issuing any
   refund.
5. **Measure.** The refund benchmark compares three configurations on 7 tasks:

| Metric | baseline | mindmesh-misconfigured | mindmesh |
|---|---|---|---|
| Task success rate | 43% | 57% | **100%** |
| Required-evidence recall | 86% | 29% | **100%** |
| Context precision | 10% | 14% | **48%** |
| Unsafe actions executed (prompt injection) | **1** | 0 | 0 |
| Recovery after injected tool faults | 0% | 0% | **100%** |

*baseline* = a typical agent stack: insertion-order context stuffing, rules only in the prompt, no
retries. Results are deterministic with the scripted model (`mindmesh bench`). Use
`--model ollama:qwen3:8b` to benchmark a real open-weight model.

## Using the SDK

```python
import asyncio
from mindmesh import AgentSpec, MemoryCreate, MindMesh, PolicyRuleIn, Condition

mm = MindMesh("sqlite:///mindmesh.db", project="my-app")   # or postgresql://…

@mm.tool(side_effect=True, description="Send money to a recipient")
async def pay(recipient: str, amount: float) -> dict:
    ...

mm.agent(AgentSpec(
    name="treasurer",
    tools=["pay"],                      # allowlist, enforced in code
    model="ollama:qwen3:8b",            # or scripted:<brain> for deterministic tests
    memory_scopes=["project", "agent:treasurer"],
))

async def main():
    await mm.init()
    await mm.remember("Vendor ACME is paid net-30.", subject_key="acme_terms")
    await mm.add_policy(PolicyRuleIn(
        name="approve-large-payments", effect="require_approval", tools=["pay"],
        conditions=[Condition(arg="amount", op="gt", value=1000)],
    ))
    run = await mm.run("treasurer", "Pay ACME's invoice #12 for $1,500")
    print(run.status)                   # waiting_approval
    [appr] = await mm.repos.approvals.list(status="pending")
    _, run = await mm.resolve_approval(appr.id, approve=True, resolver="cfo")
    print(run.result)

asyncio.run(main())
```

See [docs/sdk.md](docs/sdk.md) for the full API.

## Repository layout

```
src/mindmesh/
  core/           types, explicit state machines, event log, ids, clock
  runtime/        agent loop, tool executor, prompting/parsing
  models/         provider protocol, Ollama, scripted + recorded providers
  embeddings/     hashing (offline) and Ollama embedders
  memory/         versioned, scoped memory store
  context/        context engine + receipts
  policy/         tool registry, policy engine, rules YAML, redaction
  orchestration/  workflow DAG scheduler
  replay/         safe replay, rerun, run diff
  eval/           suites, runner, metrics, reports (suites/*.yaml)
  storage/        SQLAlchemy models, repositories (project-scoped), pgvector
  server/         FastAPI app + routers
  demo/           signature refund scenario, research-team workflow
studio/           React + TypeScript + Vite + Tailwind + shadcn/ui + React Flow
tests/            unit, integration (HTTPX), security, postgres
docs/             architecture, SDK, memory/context, policies, replay, benchmarks
```

## Testing

```bash
pytest                                   # 75 tests, offline (SQLite + scripted model)
pytest -m postgres                       # against docker compose Postgres (set MINDMESH_TEST_DATABASE_URL)
cd studio && npm test                    # Vitest component tests
cd studio && npx playwright test         # end-to-end: the signature demo through the UI
                                         # (PW_CHANNEL=msedge|chrome to use an installed browser)
```

## Documentation

- [Architecture](docs/architecture.md)
- [SDK guide](docs/sdk.md)
- [Memory & context engineering](docs/memory-and-context.md)
- [Policies & safety](docs/policies.md)
- [Tracing, replay & evaluation](docs/replay-and-evaluation.md)

## Roadmap

- Versioned schema migrations (currently `create_all()` on startup)
- Streaming token output in Execution Studio
- More benchmark suites (multi-agent research, long-horizon memory)
- OpenTelemetry export of the event log

## License

Apache-2.0
