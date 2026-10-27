# Contributing to MINDMESH

Thanks for helping. This guide gets you from a fresh clone to a merged pull request. If you only want to
*use* MINDMESH, the [quickstart](docs/quickstart.md) is the right place.

## Ways to contribute

- **Report a bug.** If it happened in an agent run, attach the run's export (`mindmesh runs export <id> -o
  bug.json`, or **Export JSON** in Studio). Anyone can then import and replay it, with no access to your code or
  model. Check it for secrets first: tool arguments and results are included.
- **Fix a bug or add a feature.** For anything larger than a small fix, open an issue first, so we can agree on
  the approach before you invest time.
- **Add an integration, a model provider or a benchmark suite.** These are the most common extension points.
  See the recipes below.
- **Improve the docs.** If something in the quickstart took you longer than it should have, that's a bug.

## Set up (10 minutes)

Requires Python ≥ 3.12 and Node ≥ 20.19.

```bash
git clone https://github.com/Mmukund-31/MINDMESH.git && cd MINDMESH
python -m venv .venv && source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[server,postgres,dev]"                     # dev includes the LangChain extra
cd studio && npm install && cd ..
pytest -q                                                   # ~1 min, offline: SQLite + scripted models
```

Run it locally:

```bash
mindmesh demo seed                 # sample data: the refund scenario, runs, a workflow
mindmesh serve --reload            # API + bundled Studio on http://127.0.0.1:8000
cd studio && npm run dev           # or: Studio with hot reload on http://localhost:5173 (proxies the API)
```

Docker Compose (Postgres + pgvector, optional Ollama) is described in the README. Copy `.env.example` to `.env`
first; use `POSTGRES_PORT=5433` if a local PostgreSQL already owns 5432.

## Where things live

| Path | What | Read first |
|---|---|---|
| `src/mindmesh/sdk.py` | `MindMesh`: the public entry point that wires everything together | [docs/sdk.md](docs/sdk.md) |
| `core/` | types, run/step state machines, the event log, ids, the clock | `core/state.py` |
| `runtime/` | the agent loop (`agent.py`), tool execution and policy checks (`executor.py`), prompts and output parsing | [docs/architecture.md](docs/architecture.md) |
| `models/` | the model provider protocol, Ollama, scripted and recorded providers | `models/base.py` |
| `memory/`, `context/` | the versioned, scoped memory store; context assembly and receipts | [docs/memory-and-context.md](docs/memory-and-context.md) |
| `policy/` | the tool registry, the policy engine, rules YAML, redaction | [docs/policies.md](docs/policies.md) |
| `replay/` | safe replay, rerun and run diffs | [docs/replay-and-evaluation.md](docs/replay-and-evaluation.md) |
| `eval/` | benchmark suites (`suites/*.yaml`), the runner and its metrics | |
| `integrations/` | adapters for other agent frameworks (LangChain) | [docs/integrations/langchain.md](docs/integrations/langchain.md) |
| `export.py` | JSON export and import of runs and benchmark results | [docs/export-format.md](docs/export-format.md) |
| `storage/` | SQLAlchemy models, project-scoped repositories, Alembic migrations | |
| `server/` | the FastAPI app, routers, auth, rate limiting; `server/studio/` is the bundled Studio build | |
| `cli.py` | the `mindmesh` command | `mindmesh --help` |
| `studio/` | React + TypeScript + Vite + Tailwind + React Flow | `studio/src/lib/api.ts` |
| `examples/` | the quickstart agent and the invoice desk example app (both tested in CI) | |

## Keep the core invariants

These are what make MINDMESH trustworthy. A change that breaks one will be asked to change.

- Every run or step status change goes through `core.state.transition()`.
- Tools execute only via `runtime.executor.ToolExecutor`, after argument validation and the policy check.
- Repositories are project-scoped; never add an unscoped query. Cross-project access must be a 404.
- Events are append-only and redacted before they are stored.
- Safe replay never executes a tool or calls a model.
- Production settings fail closed (`config.Settings.validate`).

## Test what you change

| You changed | Run |
|---|---|
| anything | `pytest -q` and `ruff check .` |
| storage or SQL | the suite on PostgreSQL: `docker compose up -d postgres`, then `MINDMESH_TEST_DATABASE_URL=postgresql://mindmesh:mindmesh@127.0.0.1:5432/mindmesh pytest -m "not ollama"`. Use a scratch database: each test starts from an empty schema |
| the schema | edit `storage/orm.py`, then `alembic revision --autogenerate -m "…"`. Review the script; it must also work on databases adopted from `create_all` (see `0002`). The migration tests fail if migrations and ORM drift apart |
| the runtime or a provider | the live suite with a real model: `ollama pull qwen3:4b`, then `pytest -m ollama tests/live` (`MINDMESH_LIVE_MODEL` to choose). It covers policies, approvals, timeouts, retries, cancellation, crash recovery and replay, and writes a proof report to `bench/results/live/` |
| Studio | `cd studio && npm run typecheck && npm test`; end to end: `npx playwright test`. Then **rebuild the bundled Studio**: `python scripts/build_studio.py` (a test fails if the bundle is older than `studio/`) |
| the quickstart or examples | `pytest tests/integration/test_examples.py`. The quickstart's code block must stay identical to `examples/quickstart/my_agent.py` |
| deployment | `scripts/verify_deployment.py` against a running server (see [docs/deployment.md](docs/deployment.md)) |

CI runs lint, the Python suite on 3.12 and 3.13, Studio typecheck/tests/build, the full suite on PostgreSQL +
pgvector, and both Docker builds.

## Recipes

**A model provider.** Implement `generate(GenerationRequest) -> ModelResponse` (`models/base.py`). Raise
`ModelProviderError(retryable=…)` so the runtime retries only faults that can succeed later. Record what the
backend reports: usage, model name, digest. Register it with `register_provider("prefix", factory)`.
`models/ollama.py` is the reference.

**A framework integration.** Map the framework's model to a provider and its tools to `ToolSpec`s (strict
argument models; `ToolRegistry.add`). Keep MindMesh driving the loop, so policies and approvals still apply.
Put it in `integrations/<name>.py` behind an optional extra in `pyproject.toml`. Add tests with the framework's
fake models (see `tests/unit/test_langchain_integration.py`) and a page under `docs/integrations/`.

**A benchmark suite.** Write a YAML file next to `eval/suites/refund.yaml`, or in your own project (see
`examples/invoice_desk/invoice_desk.yaml`). It needs an app module with `install(mm)`, `eval_setup(mm,
memory_state, faults)` and `eval_task(task)`. Keep tasks deterministic with scripted or rule-based models, so
the suite measures MindMesh rather than sampling noise.

**An API endpoint.** Add it to a router in `server/routers/` with `Depends(project_mm)` (or `admin_mm` for
management). Non-GET endpoints are refused for read-only keys unless they are marked `@allow_read_only`, so
only mark endpoints that write nothing. Add an HTTP test in `tests/integration/` or `tests/security/`.

**A Studio page.** API calls go in `studio/src/lib/api.ts` and types in `lib/types.ts`. Use the components in
`components/ui` and `components/common.tsx`. Give interactive elements a `data-testid` for the Playwright
tests.

## Pull requests

- One topic per PR, with tests. Describe the behaviour change and how you verified it.
- Run `ruff check .` and `pytest -q` locally. If you touched Studio, rebuild the bundle.
- New user-facing behaviour gets a line in the relevant doc.
- Be kind in reviews; assume good intent.

By contributing, you agree that your contributions are licensed under the Apache-2.0 license (see `LICENSE`).

## Windows notes

- Use `127.0.0.1`, not `localhost`, in database URLs: `localhost` resolves to IPv6 `::1` first, which Docker
  Desktop accepts without answering, so each new connection waits for the 10 s connect timeout.
- The CLI, server and tests select a `SelectorEventLoop` on Windows automatically (psycopg's async driver
  cannot use the default `ProactorEventLoop`). In your own scripts use `mindmesh.core.aio.run(main())`
  instead of `asyncio.run(main())` when talking to PostgreSQL.
- With **Smart App Control** on, Windows blocks unsigned native files: the venv's `.exe` launchers and
  SQLAlchemy's compiled extensions. Run tools as modules (`python -m mindmesh.cli …`, `python -m pytest`,
  `python -m ruff`) and install SQLAlchemy without its extensions (same behaviour, pure Python):
  `set DISABLE_SQLALCHEMY_CEXT=1 && python -m pip install --force-reinstall --no-deps --no-binary sqlalchemy sqlalchemy`
- Playwright: `set PW_CHANNEL=msedge && npx playwright test` uses the installed Edge.
