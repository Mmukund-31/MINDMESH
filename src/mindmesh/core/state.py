"""Explicit state machines for runs, steps, workflow tasks and approvals.

Every status change in MindMesh goes through :func:`transition`, so illegal
moves (e.g. resurrecting a cancelled run) fail loudly instead of silently
corrupting execution state.
"""

from __future__ import annotations

from enum import StrEnum

from .errors import InvalidTransition


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(StrEnum):
    PLANNED = "planned"
    EXECUTING = "executing"
    DONE = "done"
    FAILED = "failed"
    BLOCKED = "blocked"


class TaskStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


TERMINAL_RUN = {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}
TERMINAL_TASK = {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.SKIPPED, TaskStatus.CANCELLED}

RUN_TRANSITIONS: dict[RunStatus, set[RunStatus]] = {
    RunStatus.PENDING: {RunStatus.RUNNING, RunStatus.CANCELLED, RunStatus.FAILED},
    RunStatus.RUNNING: {RunStatus.WAITING_APPROVAL, RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED},
    RunStatus.WAITING_APPROVAL: {RunStatus.RUNNING, RunStatus.CANCELLED, RunStatus.FAILED},
    RunStatus.SUCCEEDED: set(),
    RunStatus.FAILED: set(),
    RunStatus.CANCELLED: set(),
}

STEP_TRANSITIONS: dict[StepStatus, set[StepStatus]] = {
    StepStatus.PLANNED: {StepStatus.EXECUTING, StepStatus.BLOCKED},
    StepStatus.EXECUTING: {StepStatus.DONE, StepStatus.FAILED, StepStatus.BLOCKED},
    StepStatus.DONE: set(),
    StepStatus.FAILED: set(),
    StepStatus.BLOCKED: set(),
}

TASK_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.READY, TaskStatus.SKIPPED, TaskStatus.CANCELLED},
    TaskStatus.READY: {TaskStatus.RUNNING, TaskStatus.SKIPPED, TaskStatus.CANCELLED},
    TaskStatus.RUNNING: {
        TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.READY, TaskStatus.PENDING, TaskStatus.CANCELLED,
    },  # READY = retry, PENDING = verifier waiting for a redo
    TaskStatus.SUCCEEDED: {TaskStatus.READY, TaskStatus.PENDING},  # verifier rejection re-opens a task
    TaskStatus.FAILED: set(),
    TaskStatus.SKIPPED: set(),
    TaskStatus.CANCELLED: set(),
}

APPROVAL_TRANSITIONS: dict[ApprovalStatus, set[ApprovalStatus]] = {
    ApprovalStatus.PENDING: {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED, ApprovalStatus.EXPIRED},
    ApprovalStatus.APPROVED: set(),
    ApprovalStatus.REJECTED: set(),
    ApprovalStatus.EXPIRED: set(),
}

_TABLES = {
    RunStatus: ("run", RUN_TRANSITIONS),
    StepStatus: ("step", STEP_TRANSITIONS),
    TaskStatus: ("task", TASK_TRANSITIONS),
    ApprovalStatus: ("approval", APPROVAL_TRANSITIONS),
}


def can_transition(src: StrEnum, dst: StrEnum) -> bool:
    _, table = _TABLES[type(src)]
    return dst in table[src]  # type: ignore[index]


def transition[S: StrEnum](src: S, dst: S) -> S:
    """Validate ``src -> dst`` and return ``dst``; raise :class:`InvalidTransition` otherwise."""
    kind, table = _TABLES[type(src)]
    if dst not in table[src]:  # type: ignore[index]
        raise InvalidTransition(kind, src.value, dst.value)
    return dst
