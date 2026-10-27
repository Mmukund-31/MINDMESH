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
  First it reconciles the step that was in flight with the events written after that checkpoint
  (recorded as `run.resumed.inflight`):

  | Event log shows | Recovery |
  |---|---|
  | `step.finished` without its checkpoint | the step is kept as recorded; a recorded final answer ends the run without a new model call |
  | `approval.requested` | the pause is restored (no second approval is created) |
  | the tool finished (`tool.finished` / `tool.failed`) | its recorded result is used; the tool does **not** run again |
  | a side-effecting tool started but never finished | **not re-executed**: the model gets an error saying the outcome is unknown (`guard.triggered: unsafe_reexecution`), and the call still counts toward per-run limits such as `one-refund-per-run` |
  | nothing, or only a read-only tool started | the step is redone |

  Process shutdown (task cancellation without a cancel request) leaves the run `RUNNING` so this
  recovery can pick it up.
- **Cancellation**: `mm.cancel()` or the `cancel_requested` flag (set by any process) interrupts an
  in-flight model call within `CANCEL_POLL_S` (0.5s); tool calls are not interrupted before
  `mm.cancel()`'s 10-second grace period.
- **Model calls** are bounded by `limits.model_timeout_s` and the run's `timeout_s`. Failures are
  classified (`ModelProviderError.retryable`): timeouts, connection errors, 408/429/5xx are retried
  with backoff; unknown models and other 4xx fail the run immediately. `model.called` records the
  provider-reported model name and weights digest, stop reason, token usage (`usage_reported: false`
  marks local estimates), latency and the provider's own timing breakdown.
- **Safe replay**: `model.called` + `step.finished` events are the recording, keyed by step (for a
  step redone after recovery, only its last attempt sequence counts). A replayed action that differs
  from the recorded one emits `replay.diverged` and is not given the recorded result.

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
- **Schema management**: Alembic migrations in `src/mindmesh/storage/migrations/` (the first one also
  enables the `vector` extension on PostgreSQL). `MindMesh.init()` and server startup apply pending
  migrations; `mindmesh db upgrade` does it as a separate step. Change `storage/orm.py`, then
  `alembic revision --autogenerate -m "…"` and review the generated script.
