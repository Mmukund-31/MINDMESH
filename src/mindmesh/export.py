"""Portable JSON exports of runs and benchmark results, and import of exported runs.

A run export (``mindmesh.run/v1``) is self-contained: the run, its agent spec, every recorded event (already
redacted when it was written), checkpoints, approvals and a summary. Importing it into another database lets a
teammate inspect the trace and *safely replay* the failure (recorded model outputs and tool results, nothing is
executed), or rerun it live against their own fixes. See ``docs/export-format.md``.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

from pydantic_core import to_jsonable_python

from . import __version__
from .core import clock
from .core.events import EventType
from .core.ids import new_id
from .core.state import TERMINAL_RUN, RunStatus
from .core.types import Event, Run

if TYPE_CHECKING:
    from .sdk import MindMesh

RUN_FORMAT = "mindmesh.run/v1"
RUNS_FORMAT = "mindmesh.runs/v1"
EVAL_FORMAT = "mindmesh.eval/v1"


def _envelope(fmt: str) -> dict[str, Any]:
    return {"format": fmt, "mindmesh_version": __version__, "exported_at": clock.now().isoformat()}


def summarize(run: Run, events: list[Event]) -> dict[str, Any]:
    """The facts a reviewer looks for first: outcome, cost, and what the agent did step by step."""
    duration = None
    if run.started_at and run.ended_at:
        duration = (clock.ensure_aware(run.ended_at) - clock.ensure_aware(run.started_at)).total_seconds() * 1000
    steps = []
    for e in events:
        if e.type == EventType.STEP_FINISHED:
            a, o = e.payload.get("action", {}), e.payload.get("outcome", {})
            steps.append({"step": e.step, "action": a.get("type"), "tool": a.get("tool"), "args": a.get("args"),
                          "status": o.get("status"), "error": o.get("error")})
    decisions = Counter(e.payload.get("effect") for e in events if e.type == EventType.POLICY_DECISION)
    return {
        "status": run.status, "answer": (run.result or {}).get("answer"), "error": run.error,
        "agent": run.agent_name, "model": (run.config.get("agent_spec") or {}).get("model"),
        "models_reported": sorted({e.payload.get("model_reported") or e.payload.get("model")
                                   for e in events if e.type == EventType.MODEL_CALLED} - {None}),
        "steps": run.steps, "tool_calls": run.tool_calls, "tokens_in": run.tokens_in, "tokens_out": run.tokens_out,
        "duration_ms": duration, "policy_decisions": dict(decisions), "feedback": run.feedback,
        "timeline": steps,
    }


async def export_run(mm: MindMesh, run_id: str) -> dict[str, Any]:
    """Export one run of ``mm``'s project as a ``mindmesh.run/v1`` document."""
    run = await mm.repos.runs.get(run_id)
    events = await mm.repos.events.list(run_id)
    approvals = await mm.repos.approvals.list(run_id=run_id, limit=1000)
    return {
        **_envelope(RUN_FORMAT),
        "summary": summarize(run, events),
        "run": run.model_dump(mode="json"),
        "events": [e.model_dump(mode="json") for e in events],
        "checkpoints": to_jsonable_python(await mm.repos.runs.list_checkpoints(run_id)),
        "approvals": [a.model_dump(mode="json") for a in approvals],
    }


async def export_runs(mm: MindMesh, run_ids: list[str] | None = None, **filters: Any) -> dict[str, Any]:
    """Export several runs (``run_ids``, or the newest runs matching ``runs.list`` filters)."""
    if run_ids is None:
        run_ids = [r.id for r in await mm.repos.runs.list(**filters)]
    return {**_envelope(RUNS_FORMAT), "runs": [await export_run(mm, rid) for rid in run_ids]}


def eval_to_dict(row: Any) -> dict[str, Any]:
    return {"id": row.id, "suite": row.suite, "variant": row.variant, "model": row.model, "seed": row.seed,
            "metrics": row.metrics, "results": row.results, "created_at": clock.ensure_aware(row.created_at).isoformat()}


async def export_evals(mm: MindMesh, eval_ids: list[str] | None = None, *, suite: str | None = None,
                       limit: int = 100) -> dict[str, Any]:
    """Export benchmark results: per-variant metrics and per-task results (``mindmesh.eval/v1``)."""
    rows = ([await mm.repos.evals.get(i) for i in eval_ids] if eval_ids is not None
            else await mm.repos.evals.list(suite=suite, limit=limit))
    return {**_envelope(EVAL_FORMAT), "evals": [eval_to_dict(r) for r in rows]}


async def import_run(mm: MindMesh, doc: dict[str, Any]) -> Run:
    """Import a ``mindmesh.run/v1`` export into ``mm``'s project under new ids and return the new run.

    Only finished runs can be imported. The copy is labelled with its origin; replay it with ``mm.replay``."""
    from .storage.orm import EventRow

    if doc.get("format") != RUN_FORMAT:
        raise ValueError(f"not a {RUN_FORMAT} document (format={doc.get('format')!r})")
    src = Run.model_validate(doc["run"])
    if RunStatus(src.status) not in TERMINAL_RUN:
        raise ValueError(f"only finished runs can be imported; {src.id} is {src.status}")
    if "agent_spec" not in src.config:
        raise ValueError("the export has no agent spec (config.agent_spec)")
    origin = {"run_id": src.id, "project_id": src.project_id, "exported_at": doc.get("exported_at"),
              "mindmesh_version": doc.get("mindmesh_version")}
    run = await mm.repos.runs.create(
        agent_name=src.agent_name, task=src.task, input=src.input, status=src.status,
        label=f"imported from {src.id}", kind=src.kind, config={**src.config, "imported_from": origin},
        result=src.result, error=src.error, feedback=src.feedback, steps=src.steps, tool_calls=src.tool_calls,
        tokens_in=src.tokens_in, tokens_out=src.tokens_out, started_at=src.started_at, ended_at=src.ended_at,
    )
    rows = []
    for raw in doc.get("events", []):
        e = Event.model_validate(raw)
        rows.append(EventRow(id=new_id("evt"), project_id=mm.project_id, run_id=run.id, seq=e.seq, type=e.type,
                             step=e.step, span_id=e.span_id.replace(src.id, run.id),
                             parent_span_id=e.parent_span_id.replace(src.id, run.id) if e.parent_span_id else None,
                             ts=e.ts, duration_ms=e.duration_ms, payload=e.payload))
    async with mm.db.session() as s:
        s.add_all(rows)
    return run
