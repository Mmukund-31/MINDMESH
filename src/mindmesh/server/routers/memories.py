from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from ...core.types import ContextConfig, Memory, MemoryCreate, MemoryUpdate
from ...memory.impact import memory_change_impact
from ...sdk import MindMesh
from ..deps import allow_read_only, project_mm

router = APIRouter(tags=["memory"])


class RetractBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=2000)
    by: str = "user"


class ContextPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=5000)
    agent: str | None = None
    scopes: list[str] | None = None
    context: ContextConfig | None = None


class ImpactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    change: MemoryUpdate
    run_ids: list[str] | None = Field(default=None, max_length=20)


@router.get("/memories", response_model=list[Memory])
async def list_memories(
    status: str | None = None,
    kind: str | None = None,
    scope: str | None = None,
    subject_key: str | None = None,
    q: str | None = None,
    tag: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    mm: MindMesh = Depends(project_mm),
):
    return await mm.memory.list(status=status, kind=kind, scope=scope, subject_key=subject_key, text=q, tag=tag,
                                limit=limit, offset=offset)


@router.post("/memories", response_model=Memory, status_code=201)
async def create_memory(body: MemoryCreate, mm: MindMesh = Depends(project_mm)):
    return await mm.memory.add(body)


@router.get("/memories/search")
async def search_memories(
    q: str = Query(min_length=1, max_length=2000), k: int = Query(10, ge=1, le=100),
    scopes: list[str] | None = Query(None), include_inactive: bool = False,
    mm: MindMesh = Depends(project_mm),
):
    hits = await mm.memory.search(q, k=k, scopes=scopes, include_inactive=include_inactive)
    return [
        {"memory": h.memory, "similarity": round(h.similarity, 4), "keyword": round(h.keyword, 4),
         "relevance": round(h.relevance, 4)}
        for h in hits
    ]


@router.get("/memories/conflicts")
async def memory_conflicts(mm: MindMesh = Depends(project_mm)):
    return await mm.memory.conflicts()


@router.post("/memories/expire")
async def expire_memories(mm: MindMesh = Depends(project_mm)):
    return {"expired": await mm.memory.expire_due()}


@router.get("/memories/{memory_id}", response_model=Memory)
async def get_memory(memory_id: str, mm: MindMesh = Depends(project_mm)):
    return await mm.memory.get(memory_id)


@router.patch("/memories/{memory_id}", response_model=Memory)
async def update_memory(memory_id: str, body: MemoryUpdate, mm: MindMesh = Depends(project_mm)):
    return await mm.memory.update(memory_id, body)


@router.post("/memories/{memory_id}/impact")
@allow_read_only
async def memory_impact(memory_id: str, body: ImpactRequest, mm: MindMesh = Depends(project_mm)):
    """Explain an edit before applying it: visibility per agent, memories it would supersede, and how the
    context of the runs that retrieved this memory would change. Nothing is written."""
    return await memory_change_impact(mm, memory_id, body.change, run_ids=body.run_ids)


@router.post("/memories/{memory_id}/retract", response_model=Memory)
async def retract_memory(memory_id: str, body: RetractBody, mm: MindMesh = Depends(project_mm)):
    return await mm.memory.retract(memory_id, body.reason, body.by)


@router.get("/memories/{memory_id}/versions", response_model=list[Memory])
async def memory_versions(memory_id: str, mm: MindMesh = Depends(project_mm)):
    return await mm.memory.versions(memory_id)


@router.get("/memories/{memory_id}/retrievals")
async def memory_retrievals(memory_id: str, mm: MindMesh = Depends(project_mm)):
    return await mm.memory.retrievals(memory_id)


@router.post("/context/preview")
@allow_read_only
async def context_preview(body: ContextPreview, mm: MindMesh = Depends(project_mm)):
    """Dry-run context assembly: what would this agent see for this query? (not recorded)"""
    spec = mm.agents.get(body.agent) if body.agent else None
    cfg = body.context or (spec.context if spec else ContextConfig())
    scopes = body.scopes or (spec.memory_scopes if spec else ["project"])
    return await mm.context.assemble(query=body.query, config=cfg, scopes=scopes, record=False)
