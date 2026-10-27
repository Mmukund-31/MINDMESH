"""Explain a memory edit before it is applied.

A dry run of :meth:`MemoryStore.update`: which agents gain or lose sight of the memory, which memories the new
version would supersede, and how the context of the runs that retrieved it would change. The context engine
runs on rewritten candidate rows (``assemble(simulate=...)``), so nothing is written or recorded.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import inspect as sa_inspect

from ..core import clock
from ..core.events import EventType
from ..core.types import AgentSpec, ContextItem, ContextReceipt, MemoryStatus, MemoryUpdate
from ..storage.orm import MemoryRow
from ..storage.vector import cosine
from .store import scope_visible

if TYPE_CHECKING:
    from ..sdk import MindMesh

MAX_RUNS = 6
PREVIEW_ID = "new-version"  # item id of the not-yet-written version in previewed receipts


def _clone(row: MemoryRow, **changes: Any) -> MemoryRow:
    """A detached copy: the dry run must never touch session-bound rows."""
    data = {a.key: getattr(row, a.key) for a in sa_inspect(MemoryRow).column_attrs}
    return MemoryRow(**(data | changes))


def _brief(item: ContextItem) -> dict[str, Any]:
    return {"item_id": item.item_id, "subject_key": item.subject_key, "scope": item.scope, "content": item.content,
            "reason": item.reason.value if item.reason else None, "detail": item.detail}


def _diff(before: ContextReceipt, after: ContextReceipt, src_id: str) -> dict[str, Any]:
    def ids(r: ContextReceipt) -> set[str]:
        # the edited memory and its preview are one lineage: compare them as the same item
        return {src_id if i.item_id == PREVIEW_ID else i.item_id for i in r.included if i.kind == "memory"}

    b, a = ids(before), ids(after)
    after_items = {src_id if i.item_id == PREVIEW_ID else i.item_id: i for i in after.included + after.excluded}
    return {
        "newly_included": [_brief(i) for i in after.included if i.kind == "memory"
                           and (src_id if i.item_id == PREVIEW_ID else i.item_id) not in b],
        "newly_excluded": [_brief(after_items[i]) if i in after_items else
                           _brief(next(x for x in before.included if x.item_id == i)) for i in sorted(b - a)],
        "used_tokens": {"before": before.used_tokens, "after": after.used_tokens},
    }


async def memory_change_impact(
    mm: MindMesh, memory_id: str, patch: MemoryUpdate, *, run_ids: list[str] | None = None
) -> dict[str, Any]:
    src = await mm.memory.repo.get(memory_id)
    if src.status != MemoryStatus.ACTIVE.value:
        raise ValueError(f"cannot edit a {src.status} memory; edit the active version instead")
    scope = patch.scope if patch.scope is not None else src.scope
    content = patch.content if patch.content is not None else src.content

    superseded = [src]
    if src.subject_key and scope != src.scope:
        superseded += [o for o in await mm.memory.repo.active_for_subject(src.subject_key, scope) if o.id != src.id]
    if content == src.content:
        vec = src.embedding
    else:
        [vec] = await mm.memory.embedder.embed([mm.memory._embed_text(src.subject_key, content)])
    now = clock.now()
    preview = _clone(
        src, id=PREVIEW_ID, version=src.version + 1, content=content, scope=scope,
        trust=patch.trust if patch.trust is not None else src.trust,
        importance=patch.importance if patch.importance is not None else src.importance,
        expires_at=patch.expires_at if patch.expires_at is not None else src.expires_at,
        status=MemoryStatus.ACTIVE.value, status_reason=None, supersedes_id=src.id, embedding=vec,
        valid_from=now, created_at=now, created_by=patch.edited_by,
    )
    gone = {m.id for m in superseded}

    async def simulate(rows, qvec):
        out = [(_clone(r, status=MemoryStatus.SUPERSEDED.value, status_reason="superseded by the new version"), s)
               if r.id in gone else (r, s) for r, s in rows]
        return out + [(preview, cosine(qvec, vec) if vec is not None else 0.0)]

    agents = [
        {"agent": a.name, "scopes": a.memory_scopes, "before": scope_visible(src.scope, a.memory_scopes),
         "after": scope_visible(scope, a.memory_scopes)}
        for a in mm.agents.values()
    ]

    if run_ids is None:
        run_ids = []
        for v in await mm.memory.repo.versions(src.lineage_id):
            for r in await mm.memory.repo.retrievals(v.id):
                if r.run_id and r.run_id not in run_ids:
                    run_ids.append(r.run_id)
    runs = []
    for run_id in run_ids:
        if len(runs) >= MAX_RUNS:
            break
        run = await mm.repos.runs.get(run_id)
        if run.kind in ("replay", "eval"):
            continue
        receipts = await mm.repos.events.list(run_id, types=[EventType.CONTEXT_ASSEMBLED])
        if not receipts:
            continue
        recorded = ContextReceipt.model_validate(receipts[0].payload)
        spec = AgentSpec.model_validate(run.config["agent_spec"])
        pinned = [i for i in recorded.included if i.kind == "task"]

        async def assemble(sim=None, *, spec=spec, recorded=recorded, pinned=pinned):
            return await mm.context.assemble(
                query=recorded.query, config=spec.context, scopes=spec.memory_scopes, step=recorded.step,
                pinned=[p.model_copy() for p in pinned], record=False, simulate=sim,
            )

        before, after = await assemble(), await assemble(simulate)
        runs.append({"run_id": run.id, "agent": run.agent_name, "kind": run.kind, "task": run.task[:200],
                     "answer": (run.result or {}).get("answer"), "query": recorded.query,
                     **_diff(before, after, src.id)})

    return {
        "memory": {"id": src.id, "subject_key": src.subject_key, "version": src.version},
        "changes": {
            k: {"before": b, "after": a}
            for k, b, a in [
                ("content", src.content, content), ("scope", src.scope, scope),
                ("trust", src.trust, preview.trust), ("importance", src.importance, preview.importance),
            ]
            if b != a
        },
        "new_version": src.version + 1,
        "supersedes": [{"id": m.id, "subject_key": m.subject_key, "scope": m.scope, "content": m.content,
                        "version": m.version} for m in superseded],
        "visibility": agents,
        "runs": runs,
    }
