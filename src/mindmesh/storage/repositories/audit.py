from __future__ import annotations

from typing import Any

from sqlalchemy import select

from ...core.ids import new_id
from ..orm import AuditRow
from .base import ScopedRepo


class AuditRepo(ScopedRepo):
    async def record(self, *, actor: str, action: str, target_type: str, target_id: str | None, summary: str,
                     details: dict[str, Any] | None = None) -> AuditRow:
        row = AuditRow(id=new_id("aud"), project_id=self.project_id, actor=actor, action=action,
                       target_type=target_type, target_id=target_id, summary=summary, details=details or {})
        async with self.db.session() as s:
            s.add(row)
        return row

    async def list(self, *, target_type: str | None = None, limit: int = 200) -> list[AuditRow]:
        q = select(AuditRow).where(AuditRow.project_id == self.project_id)
        if target_type:
            q = q.where(AuditRow.target_type == target_type)
        q = q.order_by(AuditRow.created_at.desc(), AuditRow.id.desc()).limit(limit)
        async with self.db.session() as s:
            return list((await s.execute(q)).scalars())
