from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from ...core.events import EventType
from ...core.state import TERMINAL_RUN, RunStatus
from ...core.types import Event, Run, RunCreate, RunFeedback, RunOverrides
from ...sdk import MindMesh
from ..deps import project_mm, stream_mm
from ..tokens import issue_stream_token
from ..trace import build_trace

router = APIRouter(tags=["runs"])

MAX_STREAM_S = 30 * 60  # clients reconnect with ?after=<last seq>


@router.post("/runs", response_model=Run, status_code=201)
async def create_run(body: RunCreate, mm: MindMesh = Depends(project_mm)):
    return await mm.run(body.agent, body.task, body.input, overrides=body.overrides, label=body.label, wait=False)


@router.get("/runs", response_model=list[Run])
async def list_runs(
    status: str | None = None,
    agent: str | None = None,
    kind: str | None = None,
    workflow_run_id: str | None = None,
    parent_run_id: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    mm: MindMesh = Depends(project_mm),
):
    return await mm.repos.runs.list(status=status, agent=agent, kind=kind, workflow_run_id=workflow_run_id,
                                    parent_run_id=parent_run_id, limit=limit, offset=offset)


@router.get("/runs/{run_id}", response_model=Run)
async def get_run(run_id: str, mm: MindMesh = Depends(project_mm)):
    return await mm.repos.runs.get(run_id)


@router.post("/runs/{run_id}/cancel", response_model=Run)
async def cancel_run(run_id: str, mm: MindMesh = Depends(project_mm)):
    return await mm.cancel(run_id)


@router.post("/runs/{run_id}/feedback", response_model=Run)
async def run_feedback(run_id: str, body: RunFeedback, mm: MindMesh = Depends(project_mm)):
    await mm.repos.runs.get(run_id)
    return await mm.repos.runs.update(run_id, feedback=body.model_dump(mode="json"))


@router.post("/runs/{run_id}/resume", response_model=Run)
async def resume_run(run_id: str, mm: MindMesh = Depends(project_mm)):
    return await mm.resume(run_id, wait=False)


@router.get("/runs/{run_id}/events", response_model=list[Event])
async def run_events(run_id: str, after: int = Query(0, ge=0), type: list[str] | None = Query(None), mm: MindMesh = Depends(project_mm)):
    await mm.repos.runs.get(run_id)
    return await mm.repos.events.list(run_id, after_seq=after, types=type)


@router.get("/runs/{run_id}/trace")
async def run_trace(run_id: str, mm: MindMesh = Depends(project_mm)):
    run = await mm.repos.runs.get(run_id)
    trace = build_trace(await mm.repos.events.list(run_id))
    approvals = await mm.repos.approvals.list(run_id=run_id)
    children = await mm.repos.runs.list(parent_run_id=run_id, limit=20)
    return {"run": run, **trace, "approvals": approvals, "children": children}


@router.get("/runs/{run_id}/receipts")
async def run_receipts(run_id: str, mm: MindMesh = Depends(project_mm)):
    await mm.repos.runs.get(run_id)
    return [e.payload for e in await mm.repos.events.list(run_id, types=[EventType.CONTEXT_ASSEMBLED])]


@router.get("/runs/{run_id}/checkpoints")
async def run_checkpoints(run_id: str, mm: MindMesh = Depends(project_mm)):
    await mm.repos.runs.get(run_id)
    return await mm.repos.runs.list_checkpoints(run_id)


@router.post("/runs/{run_id}/stream-token")
async def stream_token(run_id: str, request: Request, mm: MindMesh = Depends(project_mm)):
    """A short-lived token for ``GET /runs/{run_id}/stream?token=…``, so EventSource clients (which cannot
    send headers) never put the API key in a URL. Only valid for this run, in this project."""
    await mm.repos.runs.get(run_id)
    settings = request.app.state.settings
    ttl = settings.stream_token_ttl_s
    return {"token": issue_stream_token(settings.resolved_secret_key(), mm.project_id, run_id, ttl), "expires_in": ttl}


@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: str, request: Request, after: int = Query(0, ge=0), mm: MindMesh = Depends(stream_mm)):
    """Server-sent events: one ``event`` message per log entry, ``run`` messages on status changes.

    Authenticate with the ``X-API-Key`` header or a ``token`` from ``POST /runs/{run_id}/stream-token``.
    """
    await mm.repos.runs.get(run_id)

    async def gen():
        last = after
        last_status = None
        idle_after_terminal = 0
        deadline = time.monotonic() + MAX_STREAM_S
        while True:
            if await request.is_disconnected():
                return
            if time.monotonic() > deadline:
                yield f"event: timeout\ndata: {json.dumps({'after': last})}\n\n"
                return
            for e in await mm.repos.events.list(run_id, after_seq=last, limit=500):
                last = e.seq
                yield f"id: {e.seq}\nevent: event\ndata: {e.model_dump_json()}\n\n"
            run = await mm.repos.runs.get(run_id)
            if run.status != last_status:
                last_status = run.status
                yield f"event: run\ndata: {run.model_dump_json()}\n\n"
            if RunStatus(run.status) in TERMINAL_RUN or run.status == RunStatus.WAITING_APPROVAL.value:
                idle_after_terminal += 1
                if idle_after_terminal > 2:
                    yield f"event: end\ndata: {json.dumps({'status': run.status})}\n\n"
                    return
            await asyncio.sleep(0.4)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/runs/{run_id}/replay", response_model=Run, status_code=201)
async def replay_run(run_id: str, mm: MindMesh = Depends(project_mm)):
    return await mm.replay(run_id, wait=False)


@router.post("/runs/{run_id}/rerun", response_model=Run, status_code=201)
async def rerun_run(run_id: str, overrides: RunOverrides | None = None, mm: MindMesh = Depends(project_mm)):
    return await mm.rerun(run_id, overrides, wait=False)


@router.get("/compare")
async def compare(a: str, b: str, mm: MindMesh = Depends(project_mm)):
    return await mm.compare(a, b)
