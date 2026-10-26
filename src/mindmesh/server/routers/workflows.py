from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from ...core.types import WorkflowSpec
from ...sdk import MindMesh
from ..deps import project_mm

router = APIRouter(tags=["orchestration"])


class WorkflowStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template: str | None = None
    spec: WorkflowSpec | None = None


def _templates() -> dict[str, WorkflowSpec]:
    from ...demo import research

    return {research.TEMPLATE.name: research.TEMPLATE}


def _row(r) -> dict:
    return {"id": r.id, "name": r.name, "goal": r.goal, "status": r.status, "created_at": r.created_at,
            "ended_at": r.ended_at}


@router.get("/workflows/templates")
async def templates():
    return [t.model_dump(mode="json") for t in _templates().values()]


@router.get("/workflows")
async def list_workflows(mm: MindMesh = Depends(project_mm)):
    out = []
    for r in await mm.repos.workflows.list_runs():
        tasks = await mm.repos.workflows.tasks(r.id)
        out.append(_row(r) | {"tasks": len(tasks), "succeeded": sum(t.status == "succeeded" for t in tasks)})
    return out


@router.post("/workflows", status_code=201)
async def start_workflow(body: WorkflowStart, mm: MindMesh = Depends(project_mm)):
    if body.spec is None and body.template is None:
        raise ValueError("provide either 'template' or 'spec'")
    spec = body.spec or _templates().get(body.template or "")
    if spec is None:
        raise ValueError(f"unknown template {body.template!r}")
    if spec.name == "research-brief":
        from ...demo import research

        research.reset_faults()
    wid = await mm.run_workflow(spec, wait=False)
    return _row(await mm.repos.workflows.get_run(wid))


@router.get("/workflows/{wid}")
async def get_workflow(wid: str, mm: MindMesh = Depends(project_mm)):
    run = await mm.repos.workflows.get_run(wid)
    return {
        **_row(run),
        "spec": run.spec,
        "tasks": await mm.repos.workflows.tasks(wid),
        "evidence": await mm.repos.workflows.evidence(wid),
        "events": await mm.repos.events.list(wid),
        "runs": await mm.repos.runs.list(workflow_run_id=wid, limit=200),
    }
