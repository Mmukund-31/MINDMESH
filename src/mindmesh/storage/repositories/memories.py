from __future__ import annotations

from typing import Any

from sqlalchemy import Float, bindparam, or_, select, update

from ...core.errors import NotFound
from ...core.ids import new_id
from ..orm import MemoryRetrievalRow, MemoryRow
from ..vector import cosine
from .base import ScopedRepo


class MemoryRepo(ScopedRepo):
    async def insert(self, row: MemoryRow, *, supersede_id: str | None = None, reason: str | None = None) -> MemoryRow:
        """Insert ``row``; optionally mark ``supersede_id`` superseded in the same transaction."""
        row.project_id = self.project_id
        async with self.db.session() as s:
            if supersede_id:
                old = await s.get(MemoryRow, supersede_id)
                if old is None or old.project_id != self.project_id:
                    raise NotFound(f"memory {supersede_id} not found")
                old.status = "superseded"
                old.status_reason = reason or f"superseded by {row.id}"
            s.add(row)
        return row

    async def get(self, memory_id: str) -> MemoryRow:
        async with self.db.session() as s:
            row = await s.get(MemoryRow, memory_id)
            if row is None or row.project_id != self.project_id:
                raise NotFound(f"memory {memory_id} not found")
            return row

    async def list(
        self,
        *,
        status: str | None = None,
        kind: str | None = None,
        scope: str | None = None,
        subject_key: str | None = None,
        text: str | None = None,
        tag: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[MemoryRow]:
        q = select(MemoryRow).where(MemoryRow.project_id == self.project_id)
        if status:
            q = q.where(MemoryRow.status == status)
        if kind:
            q = q.where(MemoryRow.kind == kind)
        if scope:
            q = q.where(MemoryRow.scope == scope)
        if subject_key:
            q = q.where(MemoryRow.subject_key == subject_key)
        if text:
            like = f"%{text}%"
            q = q.where(or_(MemoryRow.content.ilike(like), MemoryRow.subject_key.ilike(like)))
        q = q.order_by(MemoryRow.created_at.desc(), MemoryRow.id.desc()).limit(min(limit, 1000)).offset(offset)
        async with self.db.session() as s:
            rows = list((await s.execute(q)).scalars())
        if tag:
            rows = [r for r in rows if tag in (r.tags or [])]
        return rows

    async def versions(self, lineage_id: str) -> list[MemoryRow]:
        q = (
            select(MemoryRow)
            .where(MemoryRow.project_id == self.project_id, MemoryRow.lineage_id == lineage_id)
            .order_by(MemoryRow.version)
        )
        async with self.db.session() as s:
            return list((await s.execute(q)).scalars())

    async def active_for_subject(self, subject_key: str, scope: str | None = None) -> list[MemoryRow]:
        q = select(MemoryRow).where(
            MemoryRow.project_id == self.project_id,
            MemoryRow.subject_key == subject_key,
            MemoryRow.status == "active",
        )
        if scope is not None:
            q = q.where(MemoryRow.scope == scope)
        async with self.db.session() as s:
            return list((await s.execute(q)).scalars())

    async def set_status(self, memory_id: str, status: str, reason: str | None) -> MemoryRow:
        async with self.db.session() as s:
            row = await s.get(MemoryRow, memory_id)
            if row is None or row.project_id != self.project_id:
                raise NotFound(f"memory {memory_id} not found")
            row.status = status
            row.status_reason = reason
            await s.flush()
            return row

    async def nearest(self, vector: list[float], *, k: int = 50, scan_limit: int = 5000) -> list[tuple[MemoryRow, float]]:
        """Top-k memories (any status) by cosine similarity. Uses pgvector on PostgreSQL."""
        if self.db.is_postgres:
            from pgvector.sqlalchemy import Vector

            # EmbeddingType is a TypeDecorator, so use pgvector's cosine-distance operator explicitly.
            qv = bindparam("query_vector", vector, type_=Vector())
            dist = MemoryRow.embedding.op("<=>", return_type=Float)(qv)
            q = (
                select(MemoryRow, dist.label("d"))
                .where(MemoryRow.project_id == self.project_id, MemoryRow.embedding.is_not(None))
                .order_by(dist)
                .limit(k)
            )
            async with self.db.session() as s:
                return [(r, 1.0 - float(d)) for r, d in (await s.execute(q)).all()]
        q = (
            select(MemoryRow)
            .where(MemoryRow.project_id == self.project_id)
            .order_by(MemoryRow.created_at.desc())
            .limit(scan_limit)
        )
        async with self.db.session() as s:
            rows = list((await s.execute(q)).scalars())
        scored = [(r, cosine(vector, r.embedding) if r.embedding else 0.0) for r in rows]
        scored.sort(key=lambda t: t[1], reverse=True)
        return scored[:k]

    async def record_retrievals(self, run_id: str | None, receipt_id: str, query: str, items: list[dict[str, Any]]) -> None:
        if not items:
            return
        included_ids = [i["memory_id"] for i in items if i["included"]]
        async with self.db.session() as s:
            for i in items:
                s.add(
                    MemoryRetrievalRow(
                        id=new_id("ret"),
                        project_id=self.project_id,
                        memory_id=i["memory_id"],
                        run_id=run_id,
                        receipt_id=receipt_id,
                        query=query[:2000],
                        score=i["score"],
                        included=i["included"],
                        reason=i.get("reason"),
                    )
                )
            if included_ids:
                await s.execute(
                    update(MemoryRow)
                    .where(MemoryRow.project_id == self.project_id, MemoryRow.id.in_(included_ids))
                    .values(retrieval_count=MemoryRow.retrieval_count + 1)
                )

    async def retrievals(self, memory_id: str, limit: int = 100) -> list[MemoryRetrievalRow]:
        q = (
            select(MemoryRetrievalRow)
            .where(MemoryRetrievalRow.project_id == self.project_id, MemoryRetrievalRow.memory_id == memory_id)
            .order_by(MemoryRetrievalRow.created_at.desc())
            .limit(limit)
        )
        async with self.db.session() as s:
            return list((await s.execute(q)).scalars())

    async def count_by_status(self) -> dict[str, int]:
        rows = await self.list(limit=1000)
        out: dict[str, int] = {}
        for r in rows:
            out[r.status] = out.get(r.status, 0) + 1
        return out
