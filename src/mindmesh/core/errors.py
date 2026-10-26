from __future__ import annotations


class MindMeshError(Exception):
    """Base class for all MindMesh errors."""


class InvalidTransition(MindMeshError):
    def __init__(self, kind: str, src: str, dst: str):
        super().__init__(f"illegal {kind} transition {src!r} -> {dst!r}")
        self.kind, self.src, self.dst = kind, src, dst


class NotFound(MindMeshError):
    pass


class PolicyViolation(MindMeshError):
    pass


class ToolArgumentError(MindMeshError):
    pass


class ToolTimeout(MindMeshError):
    pass


class TransientToolError(MindMeshError):
    """Raise from a tool to signal the call may succeed if retried."""


class BudgetExceeded(MindMeshError):
    pass


class RunCancelled(MindMeshError):
    pass


class ModelOutputError(MindMeshError):
    pass
