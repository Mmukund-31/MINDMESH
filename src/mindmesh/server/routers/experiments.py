"""The guided refund experiment (Studio's first-run experience)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from ...core.types import Run
from ...demo import experiment
from ...sdk import MindMesh
from ..deps import project_mm

router = APIRouter(tags=["experiments"])


class ExperimentRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: Literal["original", "injection", "faults"]
    protected: bool = True
    mode: Literal["demo", "live"] = "demo"


def _live_model(request: Request) -> str | None:
    return request.app.state.settings.model


@router.get("/experiments/refund")
async def experiment_state(request: Request, mm: MindMesh = Depends(project_mm)):
    return await experiment.state(mm, live_model=_live_model(request))


@router.post("/experiments/refund/reset")
async def experiment_reset(request: Request, mm: MindMesh = Depends(project_mm)):
    await experiment.reset(mm)
    return await experiment.state(mm, live_model=_live_model(request))


@router.post("/experiments/refund/runs", response_model=Run, status_code=201)
async def experiment_run(body: ExperimentRun, request: Request, mm: MindMesh = Depends(project_mm)):
    return await experiment.start(mm, body.scenario, protected=body.protected, mode=body.mode,
                                  live_model=_live_model(request))
