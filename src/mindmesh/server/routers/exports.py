"""JSON exports of runs and benchmark results, and import of exported runs (``mindmesh.export``)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import JSONResponse

from ... import export
from ...core.state import RunStatus
from ...core.types import Run
from ...sdk import MindMesh
from ..deps import admin_mm, project_mm

router = APIRouter(tags=["export"])


def _download(doc: dict[str, Any], filename: str) -> JSONResponse:
    return JSONResponse(doc, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/runs/{run_id}/export")
async def export_run(run_id: str, mm: MindMesh = Depends(project_mm)):
    """One run as ``mindmesh.run/v1``: summary, run, agent spec, all events, checkpoints and approvals."""
    return _download(await export.export_run(mm, run_id), f"{run_id}.json")


@router.get("/export/runs")
async def export_runs(
    status: RunStatus | None = None,
    agent: str | None = None,
    kind: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    mm: MindMesh = Depends(project_mm),
):
    """The newest runs matching the filters as ``mindmesh.runs/v1``."""
    doc = await export.export_runs(mm, status=status, agent=agent, kind=kind, limit=limit)
    return _download(doc, "runs.json")


@router.get("/evals/{eval_id}/export")
async def export_eval(eval_id: str, mm: MindMesh = Depends(project_mm)):
    return _download(await export.export_evals(mm, [eval_id]), f"{eval_id}.json")


@router.get("/export/evals")
async def export_evals(suite: str | None = None, limit: int = Query(100, ge=1, le=500),
                       mm: MindMesh = Depends(project_mm)):
    """Benchmark results (metrics per variant and per-task results) as ``mindmesh.eval/v1``."""
    return _download(await export.export_evals(mm, suite=suite, limit=limit), "evals.json")


@router.post("/runs/import", response_model=Run, status_code=201)
async def import_run(doc: dict[str, Any] = Body(...), mm: MindMesh = Depends(admin_mm)):
    """Import a ``mindmesh.run/v1`` export under new ids; replay it with ``POST /runs/{id}/replay``."""
    return await export.import_run(mm, doc)
