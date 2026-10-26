from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from ...core.errors import NotFound
from ...core.ids import new_id
from ...core.types import Event, Run
from ..orm import CheckpointRow, EventRow, RunRow
from .base import ScopedRepo


class RunRepo(ScopedRepo):
    async def create(self, **fields: Any) -> Run:
        row = RunRow(id=fields.pop("id", None) or new_id("run"), project_id=self.project_id, **fields)
        async with self.db.session() as s:
            s.add(row)
        return Run.model_validate(row)

    async def get(self, run_id: str) -> Run:
        async with self.db.session() as s:
            row = await s.get(RunRow, run_id)
            if row is None or row.project_id != self.project_id:
                raise NotFound(f"run {run_id} not found")
            return Run.model_validate(row)

    async def update(self, run_id: str, **fields: Any) -> Run:
        async with self.db.session() as s:
            row = await s.get(RunRow, run_id)
            if row is None or row.project_id != self.project_id:
                raise NotFound(f"run {run_id} not found")
            for k, v in fields.items():
                setattr(row, k, v)
            await s.flush()
            return Run.model_validate(row)

    async def list(
        self,
        *,
        status: str | None = None,
        agent: str | None = None,
        kind: str | None = None,
        workflow_run_id: str | None = None,
        parent_run_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Run]:
        q = select(RunRow).where(RunRow.project_id == self.project_id)
        if status:
            q = q.where(RunRow.status == status)
        if agent:
            q = q.where(RunRow.agent_name == agent)
        if kind:
            q = q.where(RunRow.kind == kind)
        if workflow_run_id:
            q = q.where(RunRow.workflow_run_id == workflow_run_id)
        if parent_run_id:
            q = q.where(RunRow.parent_run_id == parent_run_id)
        q = q.order_by(RunRow.created_at.desc(), RunRow.id.desc()).limit(min(limit, 500)).offset(offset)
        async with self.db.session() as s:
            return [Run.model_validate(r) for r in (await s.execute(q)).scalars()]

    async def all_rows(self, *, since=None) -> list[Run]:
        q = select(RunRow).where(RunRow.project_id == self.project_id)
        if since is not None:
            q = q.where(RunRow.created_at >= since)
        async with self.db.session() as s:
            return [Run.model_validate(r) for r in (await s.execute(q)).scalars()]

    # ----------------------------------------------------------------- checkpoints

    async def save_checkpoint(self, run_id: str, step: int, event_seq: int, state: dict[str, Any]) -> str:
        cid = new_id("ckpt")
        async with self.db.session() as s:
            s.add(
                CheckpointRow(
                    id=cid, project_id=self.project_id, run_id=run_id, step=step, event_seq=event_seq, state=state
                )
            )
        return cid

    async def latest_checkpoint(self, run_id: str) -> dict[str, Any] | None:
        q = (
            select(CheckpointRow)
            .where(CheckpointRow.project_id == self.project_id, CheckpointRow.run_id == run_id)
            .order_by(CheckpointRow.event_seq.desc())
            .limit(1)
        )
        async with self.db.session() as s:
            row = (await s.execute(q)).scalar_one_or_none()
            return None if row is None else {"id": row.id, "step": row.step, "event_seq": row.event_seq, "state": row.state}

    async def list_checkpoints(self, run_id: str) -> list[dict[str, Any]]:
        q = (
            select(CheckpointRow)
            .where(CheckpointRow.project_id == self.project_id, CheckpointRow.run_id == run_id)
            .order_by(CheckpointRow.event_seq)
        )
        async with self.db.session() as s:
            return [
                {"id": r.id, "step": r.step, "event_seq": r.event_seq, "created_at": r.created_at}
                for r in (await s.execute(q)).scalars()
            ]


class EventRepo(ScopedRepo):
    async def insert(self, row: EventRow) -> None:
        row.project_id = self.project_id
        async with self.db.session() as s:
            s.add(row)

    async def max_seq(self, run_id: str) -> int:
        q = select(func.max(EventRow.seq)).where(EventRow.project_id == self.project_id, EventRow.run_id == run_id)
        async with self.db.session() as s:
            return (await s.execute(q)).scalar() or 0

    async def list(
        self, run_id: str, *, after_seq: int = 0, types: list[str] | None = None, limit: int = 2000
    ) -> list[Event]:
        q = select(EventRow).where(
            EventRow.project_id == self.project_id, EventRow.run_id == run_id, EventRow.seq > after_seq
        )
        if types:
            q = q.where(EventRow.type.in_(types))
        q = q.order_by(EventRow.seq).limit(limit)
        async with self.db.session() as s:
            return [Event.model_validate(r) for r in (await s.execute(q)).scalars()]

    async def by_type(self, types: list[str], *, limit: int = 200) -> list[Event]:
        q = (
            select(EventRow)
            .where(EventRow.project_id == self.project_id, EventRow.type.in_(types))
            .order_by(EventRow.ts.desc())
            .limit(limit)
        )
        async with self.db.session() as s:
            return [Event.model_validate(r) for r in (await s.execute(q)).scalars()]
