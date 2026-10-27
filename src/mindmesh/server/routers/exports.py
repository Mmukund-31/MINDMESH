"""JSON exports of runs and benchmark results, and import of exported runs (``mindmesh.export``)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import JSONResponse, PlainTextResponse

from ... import export
from ...core.errors import NotFound
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


@router.get("/export/evals/report")
async def eval_report(suite: str, mm: MindMesh = Depends(project_mm)):
    """A Markdown report of the latest result per variant of ``suite``: metrics table and per-task outcomes."""
    from ...eval.report import to_markdown
    from ...eval.suite import load_suite

    latest: dict[str, Any] = {}
    for row in await mm.repos.evals.list(suite=suite, limit=500):
        latest.setdefault(row.variant, row)
    if not latest:
        raise NotFound(f"no benchmark results for suite {suite!r}")
    try:
        spec = load_suite(suite)
        order = [v for v in spec.variants if v in latest] + [v for v in latest if v not in spec.variants]
        described = {k: v.description for k, v in spec.variants.items()}
        description = spec.description
    except FileNotFoundError:  # a suite from the user's own project: report without its YAML descriptions
        order, described, description = list(latest), {}, ""
    rows = [latest[v] for v in order]
    report = {
        "suite": suite, "description": description, "model": ", ".join(sorted({r.model for r in rows})),
        "seed": rows[0].seed,
        "variants": {r.variant: {"metrics": r.metrics, "results": r.results, "description": described.get(r.variant, "")}
                     for r in rows},
    }
    return PlainTextResponse(to_markdown(report), media_type="text/markdown; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{suite}-report.md"'})
