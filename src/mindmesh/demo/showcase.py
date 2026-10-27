"""Showcase data: the broken refund scenario, a few runs (one with negative feedback) and a workflow, so Studio
has something to explore. Used by ``mindmesh demo seed`` and by the server for the public demo project."""

from __future__ import annotations

from collections.abc import Callable

from ..core.types import RunFeedback
from . import refund, research

CASES = [("C-1042", "A-7731"), ("C-2077", "A-8812"), ("C-2077", "A-6666"), ("C-3310", "A-9555"),
         ("C-2077", "A-9020")]


async def reset_project(mm) -> None:
    """Delete the project's memories, retrievals and policies (runs and traces are kept)."""
    from sqlalchemy import delete

    from ..storage.orm import MemoryRetrievalRow, MemoryRow, PolicyRow

    async with mm.db.session() as s:
        for tbl in (MemoryRow, MemoryRetrievalRow, PolicyRow):
            await s.execute(delete(tbl).where(tbl.project_id == mm.project_id))


async def seed(mm, *, echo: Callable[[str], None] = lambda _: None) -> None:
    """Seed ``mm``'s project. The refund and research apps must already be installed on ``mm``."""
    await reset_project(mm)
    await refund.seed(mm, memory_state="broken")
    for cid, oid in CASES:
        task, inp = refund.task_for(cid, oid)
        r = await mm.run("support", task, inp)
        if oid == "A-7731":
            await mm.repos.runs.update(r.id, feedback=RunFeedback(
                verdict="incorrect", note="Premium customer within 30 days — should be approved.",
                by="support-lead").model_dump())
        echo(f"{oid}: {r.status} {(r.result or {}).get('answer', '')[:80]}")
    research.reset_faults()
    await mm.run_workflow(research.TEMPLATE)


async def is_empty(mm) -> bool:
    return not await mm.repos.runs.list(limit=1)
