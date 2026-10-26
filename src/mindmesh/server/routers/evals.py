from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from ...core.errors import NotFound
from ...core.ids import new_id
from ...eval.runner import run_suite
from ...eval.suite import list_suites, load_suite
from ...sdk import MindMesh
from ..deps import project_mm

router = APIRouter(tags=["evaluation"])


class EvalStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    suite: str
    variants: list[str] | None = None
    model: str | None = None


def _row(r, full: bool = False) -> dict[str, Any]:
    d = {"id": r.id, "suite": r.suite, "variant": r.variant, "model": r.model, "seed": r.seed,
         "metrics": r.metrics, "created_at": r.created_at}
    if full:
        d["results"] = r.results
    return d


@router.get("/evals/suites")
async def suites():
    out = []
    for name in list_suites():
        s = load_suite(name)
        out.append({"name": s.name, "description": s.description, "agent": s.agent,
                    "variants": {k: v.description for k, v in s.variants.items()},
                    "tasks": [{"id": t.id, "description": t.description} for t in s.tasks]})
    return out


@router.post("/evals", status_code=202)
async def start_eval(body: EvalStart, request: Request, mm: MindMesh = Depends(project_mm)):
    suite = load_suite(body.suite)
    jobs: dict[str, dict[str, Any]] = request.app.state.eval_jobs
    job_id = new_id("job")
    jobs[job_id] = {"id": job_id, "project_id": mm.project_id, "suite": suite.name, "status": "running",
                    "eval_ids": [], "error": None}

    async def work():
        try:
            report = await run_suite(suite, variants=body.variants, model=body.model, store=mm)
            jobs[job_id]["eval_ids"] = [v["eval_id"] for v in report["variants"].values()]
            jobs[job_id]["status"] = "succeeded"
        except Exception as e:  # noqa: BLE001
            jobs[job_id].update(status="failed", error=f"{type(e).__name__}: {e}")

    task = asyncio.create_task(work())
    request.app.state.background.add(task)
    task.add_done_callback(request.app.state.background.discard)
    return jobs[job_id]


@router.get("/evals/jobs/{job_id}")
async def eval_job(job_id: str, request: Request, mm: MindMesh = Depends(project_mm)):
    job = request.app.state.eval_jobs.get(job_id)
    if job is None or job["project_id"] != mm.project_id:
        raise NotFound(f"job {job_id} not found")
    return job


@router.get("/evals")
async def list_evals(suite: str | None = None, mm: MindMesh = Depends(project_mm)):
    return [_row(r) for r in await mm.repos.evals.list(suite=suite)]


@router.get("/evals/{eval_id}")
async def get_eval(eval_id: str, mm: MindMesh = Depends(project_mm)):
    return _row(await mm.repos.evals.get(eval_id), full=True)
