"""API-key management for the caller's project (admin keys only). Keys are shown once, at creation."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ...sdk import MindMesh
from ..deps import admin_mm, audit

router = APIRouter(tags=["keys"])


class KeyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    role: Literal["admin", "read"] = "admin"


def _meta(row, current_hash: str | None) -> dict:
    return {"id": row.id, "name": row.name, "role": row.role, "prefix": row.prefix, "created_at": row.created_at,
            "last_used_at": row.last_used_at, "current": row.key_hash == current_hash}


@router.get("/keys")
async def list_keys(request: Request, mm: MindMesh = Depends(admin_mm)):
    return [_meta(r, request.state.key_hash) for r in await mm.db.list_api_keys(mm.project_id)]


@router.post("/keys", status_code=201)
async def create_key(body: KeyCreate, request: Request, mm: MindMesh = Depends(admin_mm)):
    key = await mm.db.create_api_key(mm.project_id, body.name, role=body.role)
    row = next(r for r in await mm.db.list_api_keys(mm.project_id) if r.prefix == key[:10] and r.name == body.name)
    await audit(request, mm, "key.created", "key", row.id, f"created {body.role} key '{body.name}' ({row.prefix}...)")
    return {**_meta(row, request.state.key_hash), "key": key}


@router.delete("/keys/{key_id}", status_code=204)
async def revoke_key(key_id: str, request: Request, mm: MindMesh = Depends(admin_mm)):
    rows = {r.id: r for r in await mm.db.list_api_keys(mm.project_id)}
    if key_id not in rows:
        raise HTTPException(404, f"key {key_id} not found")
    if rows[key_id].key_hash == request.state.key_hash:
        raise HTTPException(409, "refusing to revoke the key used for this request (use another admin key)")
    await mm.db.revoke_api_key_id(key_id, mm.project_id)
    await audit(request, mm, "key.revoked", "key", key_id, f"revoked {rows[key_id].role} key '{rows[key_id].name}'")
    request.app.state.key_cache.clear()  # effective immediately on this instance
    return Response(status_code=204)
