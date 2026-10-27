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

**New here? Start with the [10-minute quickstart](docs/quickstart.md):** connect a real LangChain agent, inspect
what it did, and reproduce and fix a failure. Then explore the [invoice desk example](examples/invoice_desk).
Live demo (read-only): https://mindmesh-studio.vercel.app

```bash
pip install "mindmesh[server,langchain] @ git+https://github.com/Mmukund-31/MINDMESH.git"
mindmesh serve                          # API + Studio on http://127.0.0.1:8000
```

---

## Working on MINDMESH itself (no Docker, fully offline)

Requires Python ≥ 3.12 and Node ≥ 20.19. To *use* MINDMESH, the `pip install` above is enough (Studio is
bundled); see [CONTRIBUTING.md](CONTRIBUTING.md) to change it.

```bash
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[server,dev]"

mindmesh serve            # API on http://127.0.0.1:8000  (OpenAPI docs at /docs)
cd studio && npm install && npm run dev                 # Studio on http://localhost:5173
```

Open Studio and click **Run experiment** (on the Overview, or **Guided experiment** in the sidebar).
No seeding is needed. In about five minutes you watch the support agent wrongly deny a refund while its
trace streams in, read the context receipt that explains why, preview the memory fix and see exactly
what it will change, apply it, compare the runs before and after, run a controlled prompt-injection
attack and an injected CRM outage (each with a protected and an unprotected control run), and get a
reliability scorecard with the measured improvement spelled out. Everything runs in a sandbox: the tools
are simulated and no money moves.

Every run is labelled with how it was produced: **Demo** (deterministic scripted model), **Live model**
(e.g. `qwen3:4b`) or **Replay** (recorded outputs; no model or tool executed). To use a real model, start
the server with `MINDMESH_MODEL=ollama:qwen3:4b` and choose *Live model* in the experiment.

```bash
mindmesh demo refund      # the same story in your terminal (fail → diagnose → fix → rerun → benchmark)
mindmesh demo seed        # optional: extra runs, approvals and a workflow to explore in Studio
```

Studio uses the development API key `mm_dev_local_key_change_me` by default. Set `MINDMESH_API_KEY`
on the server, or create a key with `mindmesh keys create --project <name>`.

## Full stack with Docker Compose

```bash
docker compose up -d --build                         # Postgres+pgvector, API, Studio
docker compose run --rm server mindmesh demo seed    # optional demo data
open http://localhost:5173

# with a local open-weight model (downloads qwen3:8b + nomic-embed-text)
docker compose --profile llm up -d
MINDMESH_MODEL=ollama:qwen3:8b MINDMESH_EMBEDDER=ollama:nomic-embed-text docker compose --profile llm up -d server
```

## Production deployment

The server image defaults to `MINDMESH_ENV=production`. In this mode the server **refuses to start** unless:

| Variable | Requirement |
|---|---|
| `MINDMESH_DATABASE_URL` | a PostgreSQL URL (pgvector is enabled by the first migration) |
| `MINDMESH_API_KEY` | at least 32 characters, not the development key. Rotating it revokes the previous value |
| `MINDMESH_SECRET_KEY` | at least 32 characters; signs short-lived stream tokens |
| `MINDMESH_CORS_ORIGINS` | explicit `scheme://host[:port]` origins (no `*`). Empty means same-origin only |

Other settings: `MINDMESH_AUTO_MIGRATE` (default `true`), `MINDMESH_MAX_BODY_BYTES` (default 1 MiB),
`MINDMESH_STREAM_TOKEN_TTL` (default 60 s) and `MINDMESH_DOCS` (OpenAPI docs; off in production by default).
Rate limiting: `MINDMESH_RATE_LIMIT` (requests per minute per client IP, default 300) and
`MINDMESH_RATE_LIMIT_WRITES` (non-GET requests, default 60); `0` disables. Behind proxies, set uvicorn's
`FORWARDED_ALLOW_IPS` to exactly the proxies' ranges so the client is an address callers cannot forge (or set
`MINDMESH_CLIENT_IP_HEADER` to a header your edge sets itself).
A public read-only demo: `MINDMESH_PUBLIC_KEY` (a `read` key bound to `MINDMESH_PUBLIC_PROJECT`, default `demo`)
and `MINDMESH_SEED_PUBLIC=true` to seed that project on first boot. Hosted on Render + Vercel:
[docs/deployment.md](docs/deployment.md).
Generate secrets with `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

API keys are accepted only in the `X-API-Key` or `Authorization: Bearer` headers, never in URLs. Browsers
that use `EventSource` mint a token bound to one run with `POST /api/v1/runs/{id}/stream-token`, then open
`GET /api/v1/runs/{id}/stream?token=…`. Additional keys: `mindmesh keys create --project <name>` (add
`--role read` for a read-only key); list them with `mindmesh keys list` and revoke with `mindmesh keys revoke <id or key>`, or manage them in Studio under Settings.

### Schema migrations

The schema is managed by Alembic migrations shipped inside the package. The server applies pending
migrations on startup, serialised with a PostgreSQL advisory lock so replicas can start together.
To migrate as a separate release step instead, set `MINDMESH_AUTO_MIGRATE=false` (the server then refuses to
start on an outdated schema) and run:

```bash
mindmesh db upgrade      # apply pending migrations
mindmesh db current      # show the revision; exits 1 if the database is behind
```

Databases created by earlier versions (before migrations) are adopted automatically on the first upgrade.

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
  server/         FastAPI app + routers (+ studio/: the bundled Studio build)
  integrations/   LangChain (models and tools under MindMesh)
  export.py       JSON export/import of runs and benchmark results
  cli.py          `mindmesh`: serve, projects, keys, runs, evals, bench, db, demo
  demo/           signature refund scenario, research-team workflow
studio/           React + TypeScript + Vite + Tailwind + shadcn/ui + React Flow
examples/         quickstart agent, invoice_desk example app
scripts/          verify_deployment.py, build_studio.py
tests/            unit, integration (HTTPX), security, postgres, live (Ollama)
docs/             architecture, SDK, memory/context, policies, replay, benchmarks
```

## Testing

```bash
pytest                                   # offline (SQLite + scripted model)
pytest -m postgres                       # against a real PostgreSQL + pgvector (set MINDMESH_TEST_DATABASE_URL):
                                         # migrations, vector search, project isolation, persistence
cd studio && npm test                    # Vitest component tests
cd studio && npx playwright test         # end-to-end: the signature demo through the UI
                                         # (PW_CHANNEL=msedge|chrome to use an installed browser)
```

CI (`.github/workflows/ci.yml`) runs ruff, the Python suite on 3.12 and 3.13, Studio typecheck/tests/build,
the PostgreSQL suite against `pgvector/pgvector:pg16` (including a database server restart and a
production-mode server smoke test), and builds both Docker images.

## Documentation

- [Quickstart: connect a real agent in 10 minutes](docs/quickstart.md)
- [Example app: invoice desk](examples/invoice_desk/README.md)
- [LangChain integration](docs/integrations/langchain.md)
- [JSON export format](docs/export-format.md)
- [Architecture](docs/architecture.md)
- [SDK guide](docs/sdk.md)
- [Memory & context engineering](docs/memory-and-context.md)
- [Policies & safety](docs/policies.md)
- [Tracing, replay & evaluation](docs/replay-and-evaluation.md)
- [Deployment (Render + Vercel)](docs/deployment.md)

## Roadmap

- Streaming token output in Execution Studio
- More benchmark suites (multi-agent research, long-horizon memory)
- OpenTelemetry export of the event log

## License

Apache-2.0
