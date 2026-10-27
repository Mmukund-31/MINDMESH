from __future__ import annotations

from ..db import Database
from .audit import AuditRepo
from .evals import EvalRepo
from .memories import MemoryRepo
from .policies import ApprovalRepo, PolicyRepo
from .runs import EventRepo, RunRepo
from .workflows import WorkflowRepo


class Repos:
    """All repositories bound to a single project scope."""

    def __init__(self, db: Database, project_id: str):
        self.db = db
        self.project_id = project_id
        self.runs = RunRepo(db, project_id)
        self.events = EventRepo(db, project_id)
        self.memories = MemoryRepo(db, project_id)
        self.policies = PolicyRepo(db, project_id)
        self.approvals = ApprovalRepo(db, project_id)
        self.workflows = WorkflowRepo(db, project_id)
        self.evals = EvalRepo(db, project_id)
        self.audit = AuditRepo(db, project_id)


__all__ = [
    "ApprovalRepo",
    "AuditRepo",
    "EvalRepo",
    "EventRepo",
    "MemoryRepo",
    "PolicyRepo",
    "Repos",
    "RunRepo",
    "WorkflowRepo",
]
