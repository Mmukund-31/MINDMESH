"""Request-scoped dependencies: API-key authentication -> project-scoped MindMesh view."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Query, Request, status

from ..sdk import MindMesh


def root_mm(request: Request) -> MindMesh:
    return request.app.state.mm


async def project_mm(
    request: Request,
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    api_key: str | None = Query(default=None, description="For EventSource clients that cannot set headers"),
    mm: MindMesh = Depends(root_mm),
) -> MindMesh:
    key = x_api_key or api_key
    if not key and authorization and authorization.lower().startswith("bearer "):
        key = authorization[7:].strip()
    if not key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing API key (X-API-Key header)")
    cache: dict[str, str] = request.app.state.key_cache
    project_id = cache.get(key)
    if project_id is None:
        project_id = await mm.db.project_for_key(key)
        if project_id is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid API key")
        cache[key] = project_id
    return mm.scoped(project_id)
