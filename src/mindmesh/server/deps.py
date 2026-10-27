"""Request-scoped dependencies: API-key authentication -> project-scoped MindMesh view."""

from __future__ import annotations

import time

from fastapi import Depends, Header, HTTPException, Query, Request, status

from ..sdk import MindMesh
from ..storage.db import hash_key
from .tokens import verify_stream_token

KEY_CACHE_TTL_S = 30.0
KEY_CACHE_MAX = 10_000
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def allow_read_only(endpoint):
    """Mark a non-GET endpoint that only computes (preview, simulation, stream token) as usable by read keys."""
    endpoint.allow_read_only = True
    return endpoint


class KeyCache:
    """Short-lived ``key hash -> (project id, role)`` cache, so revoked keys stop working within the TTL."""

    def __init__(self, ttl_s: float = KEY_CACHE_TTL_S, max_size: int = KEY_CACHE_MAX):
        self.ttl_s, self.max_size = ttl_s, max_size
        self._entries: dict[str, tuple[tuple[str, str], float]] = {}

    def get(self, key_hash: str) -> tuple[str, str] | None:
        hit = self._entries.get(key_hash)
        if hit is None:
            return None
        if hit[1] < time.monotonic():
            del self._entries[key_hash]
            return None
        return hit[0]

    def put(self, key_hash: str, identity: tuple[str, str]) -> None:
        if len(self._entries) >= self.max_size:
            self._entries.clear()
        self._entries[key_hash] = (identity, time.monotonic() + self.ttl_s)

    def clear(self) -> None:
        self._entries.clear()


def root_mm(request: Request) -> MindMesh:
    return request.app.state.mm


async def _project_for_key(request: Request, mm: MindMesh, key: str) -> str:
    """Resolve the key's project and enforce its role; the role is kept on ``request.state.key_role``."""
    cache: KeyCache = request.app.state.key_cache
    h = hash_key(key)
    identity = cache.get(h)
    if identity is None:
        identity = await mm.db.key_identity(key)
        if identity is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid API key")
        cache.put(h, identity)
    project_id, role = identity
    request.state.key_role = role
    if role != "admin" and request.method not in SAFE_METHODS:
        if not getattr(request.scope.get("endpoint"), "allow_read_only", False):
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                "read-only API key: this is a public demo, changes are disabled")
    return project_id


def _header_key(x_api_key: str | None, authorization: str | None) -> str | None:
    if x_api_key:
        return x_api_key
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


async def project_mm(
    request: Request,
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    mm: MindMesh = Depends(root_mm),
) -> MindMesh:
    """Authenticate with ``X-API-Key`` or ``Authorization: Bearer``. Keys are never accepted in URLs."""
    key = _header_key(x_api_key, authorization)
    if not key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing API key (X-API-Key header)")
    return mm.scoped(await _project_for_key(request, mm, key))


async def stream_mm(
    request: Request,
    run_id: str,
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None, description="Stream token from POST /runs/{run_id}/stream-token "
                                                        "(for EventSource clients that cannot set headers)"),
    mm: MindMesh = Depends(root_mm),
) -> MindMesh:
    """Header auth, or a short-lived token bound to this run and project."""
    key = _header_key(x_api_key, authorization)
    if key:
        return mm.scoped(await _project_for_key(request, mm, key))
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing API key or stream token")
    project_id = verify_stream_token(request.app.state.settings.resolved_secret_key(), token, run_id)
    if project_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired stream token")
    return mm.scoped(project_id)
