from __future__ import annotations

from typing import Any

from sqlalchemy import select

from ...core.errors import NotFound
from ...core.ids import new_id
from ..orm import EvalRunRow
from .base import ScopedRepo


class EvalRepo(ScopedRepo):
    async def create(
        self, *, suite: str, variant: str, model: str, seed: int, metrics: dict[str, Any], results: list[Any]
    ) -> EvalRunRow:
        row = EvalRunRow(
            id=new_id("ev"),
            project_id=self.project_id,
            suite=suite,
            variant=variant,
            model=model,
            seed=seed,
            metrics=metrics,
            results=results,
        )
        async with self.db.session() as s:
            s.add(row)
        return row

    async def list(self, *, suite: str | None = None, limit: int = 100) -> list[EvalRunRow]:
        q = select(EvalRunRow).where(EvalRunRow.project_id == self.project_id)
        if suite:
            q = q.where(EvalRunRow.suite == suite)
        q = q.order_by(EvalRunRow.created_at.desc()).limit(limit)
        async with self.db.session() as s:
            return list((await s.execute(q)).scalars())

    async def get(self, eval_id: str) -> EvalRunRow:
        async with self.db.session() as s:
            row = await s.get(EvalRunRow, eval_id)
            if row is None or row.project_id != self.project_id:
                raise NotFound(f"eval run {eval_id} not found")
            return row
