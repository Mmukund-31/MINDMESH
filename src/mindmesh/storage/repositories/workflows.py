from __future__ import annotations

from typing import Any

from sqlalchemy import select

from ...core.errors import NotFound
from ...core.ids import new_id
from ...core.types import Evidence, WorkflowTask
from ..orm import EvidenceRow, WorkflowRunRow, WorkflowTaskRow
from .base import ScopedRepo


class WorkflowRepo(ScopedRepo):
    async def create_run(self, name: str, goal: str, spec: dict[str, Any], status: str) -> str:
        wid = new_id("wf")
        async with self.db.session() as s:
            s.add(WorkflowRunRow(id=wid, project_id=self.project_id, name=name, goal=goal, spec=spec, status=status))
        return wid

    async def get_run(self, wid: str) -> WorkflowRunRow:
        async with self.db.session() as s:
            row = await s.get(WorkflowRunRow, wid)
            if row is None or row.project_id != self.project_id:
                raise NotFound(f"workflow run {wid} not found")
            return row

    async def update_run(self, wid: str, **fields: Any) -> None:
        async with self.db.session() as s:
            row = await s.get(WorkflowRunRow, wid)
            if row is None or row.project_id != self.project_id:
                raise NotFound(f"workflow run {wid} not found")
            for k, v in fields.items():
                setattr(row, k, v)

    async def list_runs(self, limit: int = 50) -> list[WorkflowRunRow]:
        q = (
            select(WorkflowRunRow)
            .where(WorkflowRunRow.project_id == self.project_id)
            .order_by(WorkflowRunRow.created_at.desc())
            .limit(limit)
        )
        async with self.db.session() as s:
            return list((await s.execute(q)).scalars())

    async def add_task(self, wid: str, **fields: Any) -> WorkflowTask:
        row = WorkflowTaskRow(id=new_id("wt"), project_id=self.project_id, workflow_run_id=wid, **fields)
        async with self.db.session() as s:
            s.add(row)
        return WorkflowTask.model_validate(row)

    async def update_task(self, task_id: str, **fields: Any) -> WorkflowTask:
        async with self.db.session() as s:
            row = await s.get(WorkflowTaskRow, task_id)
            if row is None or row.project_id != self.project_id:
                raise NotFound(f"workflow task {task_id} not found")
            for k, v in fields.items():
                setattr(row, k, v)
            await s.flush()
            return WorkflowTask.model_validate(row)

    async def tasks(self, wid: str) -> list[WorkflowTask]:
        q = (
            select(WorkflowTaskRow)
            .where(WorkflowTaskRow.project_id == self.project_id, WorkflowTaskRow.workflow_run_id == wid)
            .order_by(WorkflowTaskRow.id)
        )
        async with self.db.session() as s:
            return [WorkflowTask.model_validate(r) for r in (await s.execute(q)).scalars()]

    async def add_evidence(
        self, wid: str, content: str, *, source: str | None, created_by: str, run_id: str | None, task_key: str | None
    ) -> Evidence:
        row = EvidenceRow(
            id=new_id("evd"),
            project_id=self.project_id,
            workflow_run_id=wid,
            run_id=run_id,
            task_key=task_key,
            content=content,
            source=source,
            created_by=created_by,
        )
        async with self.db.session() as s:
            s.add(row)
        return Evidence.model_validate(row)

    async def evidence(self, wid: str) -> list[Evidence]:
        q = (
            select(EvidenceRow)
            .where(EvidenceRow.project_id == self.project_id, EvidenceRow.workflow_run_id == wid)
            .order_by(EvidenceRow.created_at, EvidenceRow.id)
        )
        async with self.db.session() as s:
            return [Evidence.model_validate(r) for r in (await s.execute(q)).scalars()]
