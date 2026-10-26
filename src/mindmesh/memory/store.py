"""Memory store: versioned, scoped, provenance-tracked memories with lifecycle management.

Lifecycle rules
---------------
* Each memory belongs to a *lineage*; editing creates version N+1 and marks N ``superseded``.
* Writing a memory with a ``subject_key`` that already has an active memory **in the same
  scope** supersedes it (newer knowledge replaces older knowledge about the same subject).
* Retraction is explicit and keeps the row (with reason) for auditability.
* Memories past ``expires_at`` are lazily marked ``expired``.
* Active memories that disagree about the same subject across scopes are reported as conflicts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core import clock
from ..core.errors import NotFound
from ..core.ids import new_id
from ..core.types import Memory, MemoryCreate, MemoryStatus, MemoryUpdate
from ..embeddings import Embedder, tokenize
from ..storage.orm import MemoryRow
from ..storage.repositories import Repos


@dataclass
class ScoredMemory:
    memory: Memory
    similarity: float
    keyword: float
    relevance: float


def scope_visible(scope: str, allowed: list[str]) -> bool:
    """``allowed`` entries may be exact scopes or prefixes ending in ``*`` (e.g. ``agent:*``)."""
    for a in allowed:
        if a == "*" or a == scope or (a.endswith("*") and scope.startswith(a[:-1])):
            return True
    return False


def keyword_score(query_tokens: set[str], text: str) -> float:
    if not query_tokens:
        return 0.0
    doc = set(tokenize(text))
    return len(query_tokens & doc) / len(query_tokens)


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


class MemoryStore:
    def __init__(self, repos: Repos, embedder: Embedder):
        self.repos = repos
        self.repo = repos.memories
        self.embedder = embedder

    # ----------------------------------------------------------------- writes

    async def add(self, data: MemoryCreate, *, run_id: str | None = None) -> Memory:
        prov = data.provenance
        current = await self.repo.active_for_subject(data.subject_key, data.scope) if data.subject_key else []
        latest = max(current, key=lambda r: r.created_at) if current else None
        if latest is not None and _norm(latest.content) == _norm(data.content):
            return Memory.model_validate(latest)  # idempotent write
        [vec] = await self.embedder.embed([self._embed_text(data.subject_key, data.content)])
        row = MemoryRow(
            id=new_id("mem"),
            lineage_id=latest.lineage_id if latest else new_id("lin"),
            version=(latest.version + 1) if latest else 1,
            kind=data.kind.value,
            subject_key=data.subject_key,
            content=data.content,
            scope=data.scope,
            tags=list(data.tags),
            source_type=prov.source_type,
            source_ref=prov.source_ref,
            created_by=prov.created_by,
            run_id=run_id or prov.run_id,
            trust=data.trust,
            importance=data.importance,
            valid_from=data.valid_from or clock.now(),
            expires_at=data.expires_at,
            status=MemoryStatus.ACTIVE.value,
            supersedes_id=latest.id if latest else None,
            embedding=vec,
            created_at=clock.now(),
        )
        await self.repo.insert(row, supersede_id=latest.id if latest else None)
        # Any other active memories in this scope about the same subject are now stale.
        for other in current:
            if latest is not None and other.id != latest.id:
                await self.repo.set_status(other.id, MemoryStatus.SUPERSEDED.value, f"superseded by {row.id}")
        return Memory.model_validate(row)

    async def update(self, memory_id: str, patch: MemoryUpdate) -> Memory:
        """Create a new version of ``memory_id`` with ``patch`` applied."""
        src = await self.repo.get(memory_id)
        if src.status != MemoryStatus.ACTIVE.value:
            raise ValueError(f"cannot edit a {src.status} memory; edit the active version instead")
        content = patch.content if patch.content is not None else src.content
        scope = patch.scope if patch.scope is not None else src.scope
        [vec] = await self.embedder.embed([self._embed_text(src.subject_key, content)])
        row = MemoryRow(
            id=new_id("mem"),
            lineage_id=src.lineage_id,
            version=src.version + 1,
            kind=src.kind,
            subject_key=src.subject_key,
            content=content,
            scope=scope,
            tags=patch.tags if patch.tags is not None else list(src.tags or []),
            source_type="manual" if patch.content is not None else src.source_type,
            source_ref=src.source_ref,
            created_by=patch.edited_by,
            run_id=src.run_id,
            trust=patch.trust if patch.trust is not None else src.trust,
            importance=patch.importance if patch.importance is not None else src.importance,
            valid_from=clock.now(),
            expires_at=patch.expires_at if patch.expires_at is not None else src.expires_at,
            status=MemoryStatus.ACTIVE.value,
            supersedes_id=src.id,
            embedding=vec,
            created_at=clock.now(),
        )
        reason = f"edited by {patch.edited_by}" + (f": {patch.reason}" if patch.reason else "")
        await self.repo.insert(row, supersede_id=src.id, reason=reason)
        if src.subject_key and scope != src.scope:
            for other in await self.repo.active_for_subject(src.subject_key, scope):
                if other.id != row.id:
                    await self.repo.set_status(
                        other.id, MemoryStatus.SUPERSEDED.value, f"superseded by {row.id} (moved into {scope})"
                    )
        return Memory.model_validate(row)

    async def retract(self, memory_id: str, reason: str, by: str = "user") -> Memory:
        row = await self.repo.get(memory_id)
        if row.status == MemoryStatus.RETRACTED.value:
            return Memory.model_validate(row)
        row = await self.repo.set_status(memory_id, MemoryStatus.RETRACTED.value, f"retracted by {by}: {reason}")
        return Memory.model_validate(row)

    async def expire_due(self) -> int:
        n = 0
        now = clock.now()
        for row in await self.repo.list(status=MemoryStatus.ACTIVE.value, limit=1000):
            exp = clock.ensure_aware(row.expires_at)
            if exp is not None and exp <= now:
                await self.repo.set_status(row.id, MemoryStatus.EXPIRED.value, f"expired at {exp.isoformat()}")
                n += 1
        return n

    # ----------------------------------------------------------------- reads

    async def get(self, memory_id: str) -> Memory:
        return Memory.model_validate(await self.repo.get(memory_id))

    async def list(self, **filters: Any) -> list[Memory]:
        return [Memory.model_validate(r) for r in await self.repo.list(**filters)]

    async def versions(self, memory_id: str) -> list[Memory]:
        row = await self.repo.get(memory_id)
        return [Memory.model_validate(r) for r in await self.repo.versions(row.lineage_id)]

    async def search(
        self,
        query: str,
        *,
        k: int = 10,
        scopes: list[str] | None = None,
        include_inactive: bool = False,
        candidates: int = 50,
    ) -> list[ScoredMemory]:
        """Hybrid (vector + keyword) search."""
        [qvec] = await self.embedder.embed([query])
        qtok = set(tokenize(query))
        out: list[ScoredMemory] = []
        for row, sim in await self.repo.nearest(qvec, k=max(candidates, k)):
            if not include_inactive and row.status != MemoryStatus.ACTIVE.value:
                continue
            if scopes is not None and not scope_visible(row.scope, scopes):
                continue
            kw = keyword_score(qtok, f"{row.subject_key or ''} {row.content}")
            rel = 0.65 * max(sim, 0.0) + 0.35 * kw
            out.append(ScoredMemory(Memory.model_validate(row), sim, kw, rel))
        out.sort(key=lambda s: s.relevance, reverse=True)
        return out[:k]

    async def conflicts(self) -> list[dict[str, Any]]:
        """Active memories about the same subject whose content disagrees."""
        groups: dict[str, list[MemoryRow]] = {}
        for row in await self.repo.list(status=MemoryStatus.ACTIVE.value, limit=1000):
            if row.subject_key:
                groups.setdefault(row.subject_key, []).append(row)
        out = []
        for key, rows in groups.items():
            if len({_norm(r.content) for r in rows}) > 1:
                winner = max(rows, key=lambda r: (r.trust, clock.ensure_aware(r.valid_from)))
                out.append(
                    {
                        "subject_key": key,
                        "memories": [Memory.model_validate(r).model_dump(mode="json") for r in rows],
                        "suggested_winner": winner.id,
                        "rule": "highest trust, then most recent valid_from",
                    }
                )
        return out

    async def retrievals(self, memory_id: str) -> list[dict[str, Any]]:
        await self.repo.get(memory_id)  # scope check
        return [
            {
                "id": r.id,
                "run_id": r.run_id,
                "receipt_id": r.receipt_id,
                "query": r.query,
                "score": r.score,
                "included": r.included,
                "reason": r.reason,
                "created_at": r.created_at,
            }
            for r in await self.repo.retrievals(memory_id)
        ]

    @staticmethod
    def _embed_text(subject_key: str | None, content: str) -> str:
        return f"{subject_key.replace('.', ' ').replace('_', ' ')}: {content}" if subject_key else content


__all__ = ["MemoryStore", "NotFound", "ScoredMemory", "keyword_score", "scope_visible"]
