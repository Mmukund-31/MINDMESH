# Architecture

MINDMESH has three deployable parts that share one core library:

```
┌──────────────────────┐      HTTP/JSON + SSE      ┌───────────────────────────────┐
│  MINDMESH Studio      │ ───────────────────────▶ │  API server (FastAPI)          │
│  React · React Flow   │                           │  /api/v1 · API-key → project   │
└──────────────────────┘                           └──────────────┬────────────────┘
                                                                    │ same core
┌──────────────────────┐    in-process (SDK)       ┌──────────────▼────────────────┐
│  Your Python app      │ ───────────────────────▶ │  mindmesh core                 │
└──────────────────────┘                           │  runtime · memory · context    │
                                                   │  policy · orchestration ·      │
                                                   │  replay · eval                 │
                                                   └──────┬───────────────┬────────┘
                                                          │               │
                                            SQLite / PostgreSQL+pgvector  Ollama / scripted
```

The SDK and the server write to the same database, so runs executed inside your application show
up in Studio immediately.

## Core modules

| Module | Responsibility |
|---|---|
| `core/state.py` | Explicit state machines for runs, steps, workflow tasks and approvals. Every status change calls `transition()`, which raises `InvalidTransition` for illegal moves. |
| `core/events.py` | Append-only event log per run (`(run_id, seq)` is unique). Events form a span tree: run → step → context/model/policy/tool. Payloads are redacted before persistence. |
| `runtime/agent.py` | `AgentRunner`: context → model → policy → tool → event → checkpoint. Handles bounded retries, output repair, budgets (steps, tokens, wall time, tool calls), approvals, resume, crash recovery and cancellation. |
| `runtime/executor.py` | `ToolExecutor`, the **only** code path that executes tools. It runs registry lookup → strict argument validation → repeated-failure guard → tool budget → policy decision → execution with timeout and retries. In replay mode it returns recorded results instead. |
| `memory/store.py` | Versioned, scoped memories with provenance, expiry, retraction and conflict detection. |
| `context/engine.py` | Assembles context under a token budget and produces a `ContextReceipt`. |
| `policy/` | Tool registry (`@tool` → strict Pydantic arg models), `PolicyEngine`, YAML rules and the redactor. |
| `orchestration/scheduler.py` | DAG workflow execution with concurrency, handoffs, an evidence board, retries and verifiers. |
| `replay/` | Safe replay (recorded model and tool outputs), rerun with overrides, step-aligned diffs. |
| `eval/` | YAML suites, an isolated per-task runner, metrics and Markdown/JSON reports. |
| `storage/` | SQLAlchemy async models and **project-scoped repositories**. No repository method can query across projects. |
| `models/`, `embeddings/` | Pluggable providers resolved from strings (`ollama:qwen3:8b`, `scripted:<brain>`, `hashing:384`, `ollama:nomic-embed-text`). Register your own with `register_provider()`. |

## Run lifecycle

```
PENDING ──▶ RUNNING ──▶ SUCCEEDED
              │  ▲  └──▶ FAILED      (exception, budget, max steps)
              ▼  │  └──▶ CANCELLED   (cooperative cancel token / cancel_requested flag)
        WAITING_APPROVAL  ── approve/reject ──▶ resume from checkpoint
```

Each step records `step.started`, `context.assembled` (the full receipt), `model.called` (messages,
raw response, tokens), `policy.decision`, `tool.started` / `tool.retry` / `tool.finished` /
`tool.failed`, `step.finished` (action + outcome) and `checkpoint.saved`. A checkpoint stores the
serialized `RunState` (history, counters, pending approval), which allows the following:

- **Approval resume**: the paused tool call is executed (approved) or turned into a `blocked` outcome
  (rejected), and the loop continues.
- **Crash recovery**: `mindmesh.resume(run_id)` restarts a `RUNNING` run from its latest checkpoint.
- **Safe replay**: `model.called` + `step.finished` events are the recording.

## Isolation and security

- Every table carries `project_id`. API keys are stored as SHA-256 hashes and resolve to exactly one
  project. A request for another project's object returns **404**, which hides its existence.
- Tools run only after allowlist, argument-validation and policy checks. The LLM never decides
  whether a call is permitted.
- Secrets are redacted (sensitive keys, key/token patterns, card numbers, key=value pairs in text)
  in event payloads *and* in tool I/O echoed back to the model.
- Input models use `extra="forbid"`. Memory scopes are validated against a strict pattern.

## Replaceable layers

- **Storage**: `Database(url)` supports SQLite (dev/tests) and PostgreSQL. On PostgreSQL the embedding
  column is a pgvector `vector`, and nearest-neighbour search uses `<=>` in SQL. Elsewhere a portable
  cosine scan is used.
- **Models**: implement `ModelProvider.generate(GenerationRequest) -> ModelResponse`.
- **Embeddings**: implement `Embedder.embed(texts) -> list[list[float]]`.
- **Schema management**: tables (and the `vector` extension on PostgreSQL) are created idempotently with
  `create_all()` at startup. Versioned migrations are not included yet; see the roadmap in the README.
