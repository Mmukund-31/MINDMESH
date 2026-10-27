# JSON export format

Runs and benchmark results export as plain JSON, for sharing failures, attaching them to issues, archiving
them, or feeding them to your own analysis. Every document starts with the same envelope:

```json
{"format": "mindmesh.run/v1", "mindmesh_version": "0.1.0", "exported_at": "2026-10-27T12:18:41+00:00", ...}
```

`format` is versioned. A future `v2` may add or rename fields; `v1` readers can rely on everything below.

## Getting exports

| | CLI | API | Studio |
|---|---|---|---|
| One run | `mindmesh runs export <id> -o run.json` | `GET /api/v1/runs/{id}/export` | **Export JSON** on a run |
| Several runs | `mindmesh runs export [ids…] [--status failed] [--limit 20]` | `GET /api/v1/export/runs?status=&agent=&kind=&limit=` | |
| Benchmarks | `mindmesh evals export [ids…] [--suite name]` | `GET /api/v1/export/evals?suite=`, `GET /api/v1/evals/{id}/export` | **Export JSON** in Replay Lab |
| Import a run | `mindmesh runs import run.json -p <project>` | `POST /api/v1/runs/import` (admin key) | |

Read-only keys can export, but they cannot import. From the SDK, use `mindmesh.export.export_run(mm, run_id)`,
`export_runs`, `export_evals` and `import_run(mm, doc)`.

## `mindmesh.run/v1`: one run

| Field | Content |
|---|---|
| `summary` | The facts a reviewer needs first: `status`, `answer`, `error`, `agent`, `model`, `models_reported` (what the backend says it ran), `steps`, `tool_calls`, `tokens_in`/`tokens_out`, `duration_ms`, `policy_decisions` (count per effect), `feedback`, and `timeline` (one entry per step: `tool`, `args`, `status`, `error`) |
| `run` | The run record: `id`, `project_id`, `agent_name`, `task`, `input`, `status`, `kind` (`live`, `replay`, `rerun`, `eval`), `parent_run_id`, `config` (including `agent_spec`, the full agent definition used), `result`, `error`, `feedback`, counters, and timestamps |
| `events` | Every recorded event in order (`seq`): `run.created`, `context.assembled` (the context receipt: what was included or excluded and why), `model.called` (the prompt-side metadata and the raw response), `policy.decision`, `tool.started`/`tool.finished`/`tool.failed`/`tool.retry`, `approval.*`, `step.finished`, `run.state_changed`, and so on. Each has `type`, `step`, `span_id`/`parent_span_id`, `ts`, `duration_ms` and `payload` |
| `checkpoints` | Resumable state saved after each step (`step`, `event_seq`, `state`) |
| `approvals` | Approval requests with their decisions (`tool`, `args`, `reason`, `status`, `resolver`, `note`) |

**Secrets:** events are redacted when they are written, by the same redactor that protects the trace, so an
export contains nothing the trace did not. Tool arguments and results are included, so review an export before
sharing it outside your organisation.

**Importing:** `import_run` copies a finished run into the target project under new ids. The copy's label is
`imported from <original id>`, and `config.imported_from` records its origin. Its events keep their order and
payloads, which is all a **safe replay** needs: the recorded model outputs and tool results are fed back
through the runtime, nothing is executed, and the agent's code does not have to be present. A **rerun** of an
imported run executes live, so it needs the agent registered (`--app your_module`).

## `mindmesh.runs/v1`: several runs

`{"format": "mindmesh.runs/v1", …, "runs": [<mindmesh.run/v1>, …]}`. `mindmesh runs import` accepts this format
too.

## `mindmesh.eval/v1`: benchmark results

`{"format": "mindmesh.eval/v1", …, "evals": [...]}`. Each entry is one variant of one suite run:

| Field | Content |
|---|---|
| `id`, `suite`, `variant`, `model`, `seed`, `created_at` | Which run this is |
| `metrics` | `tasks`, `success_rate`, `evidence_recall`, `context_precision`, `context_efficiency`, `unsafe_actions_executed`, `unsafe_actions_blocked`, `tool_error_rate`, `recovery_rate` (null without fault-injection tasks), `approvals_requested`, `avg_steps`, `avg_tokens`, `avg_latency_ms` |
| `results` | One entry per task: `task_id`, `success`, `answer`, every `check` with `passed`, context statistics, unsafe actions executed or blocked, tool errors and retries, approvals, and the step `trace` |

`mindmesh bench` also writes each report as JSON and Markdown to `bench/results/` (`--out` to change).
