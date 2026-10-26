"""Persistent, append-only, per-run event log.

Events form a span tree: the run is the root span, each step opens a child
span, and model calls / context assembly / policy decisions / tool calls hang
off the step span. Execution Studio renders this tree as a graph.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from ..policy.redact import Redactor, default_redactor
from ..storage.orm import EventRow
from ..storage.repositories.runs import EventRepo
from . import clock
from .ids import new_id
from .types import Event

Listener = Callable[[Event], Awaitable[None] | None]


class EventType:
    RUN_CREATED = "run.created"
    RUN_STATE = "run.state_changed"
    RUN_RESUMED = "run.resumed"
    STEP_STARTED = "step.started"
    STEP_FINISHED = "step.finished"
    CONTEXT_ASSEMBLED = "context.assembled"
    MODEL_CALLED = "model.called"
    MODEL_FAILED = "model.failed"
    POLICY_DECISION = "policy.decision"
    TOOL_STARTED = "tool.started"
    TOOL_FINISHED = "tool.finished"
    TOOL_FAILED = "tool.failed"
    TOOL_RETRY = "tool.retry"
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_RESOLVED = "approval.resolved"
    CHECKPOINT_SAVED = "checkpoint.saved"
    MEMORY_WRITTEN = "memory.written"
    HANDOFF = "handoff"
    BUDGET_EXCEEDED = "budget.exceeded"
    GUARD_TRIGGERED = "guard.triggered"
    REPLAY_DIVERGED = "replay.diverged"


def _jsonable(v: Any) -> Any:
    if isinstance(v, BaseModel):
        return v.model_dump(mode="json")
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, list | tuple | set):
        return [_jsonable(x) for x in v]
    if isinstance(v, str | int | float | bool) or v is None:
        return v
    return repr(v)


class EventLog:
    def __init__(self, repo: EventRepo, run_id: str, *, redactor: Redactor | None = None, start_seq: int = 0):
        self.repo = repo
        self.run_id = run_id
        self.redactor = redactor or default_redactor
        self.seq = start_seq
        self.root_span = f"span_{run_id}"
        self.listeners: list[Listener] = []
        self._lock = asyncio.Lock()

    @classmethod
    async def resume(cls, repo: EventRepo, run_id: str, **kw: Any) -> EventLog:
        return cls(repo, run_id, start_seq=await repo.max_seq(run_id), **kw)

    async def emit(
        self,
        type: str,
        payload: dict[str, Any] | None = None,
        *,
        step: int | None = None,
        span_id: str | None = None,
        parent_span_id: str | None = None,
        duration_ms: float | None = None,
    ) -> Event:
        clean = self.redactor(_jsonable(payload or {}))
        async with self._lock:
            self.seq += 1
            row = EventRow(
                id=new_id("evt"),
                run_id=self.run_id,
                seq=self.seq,
                type=type,
                step=step,
                span_id=span_id or new_id("span"),
                parent_span_id=parent_span_id if parent_span_id is not None else (
                    None if span_id == self.root_span else self.root_span
                ),
                ts=clock.now(),
                duration_ms=duration_ms,
                payload=clean,
            )
            await self.repo.insert(row)
        ev = Event.model_validate(row)
        for listener in list(self.listeners):
            res = listener(ev)
            if asyncio.iscoroutine(res):
                await res
        return ev
