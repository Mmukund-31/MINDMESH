"""SQLAlchemy ORM schema. Every tenant-owned table carries ``project_id``."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from ..core.clock import now


class EmbeddingType(TypeDecorator):
    """pgvector ``vector`` on PostgreSQL, JSON list elsewhere (SQLite)."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            try:
                from pgvector.sqlalchemy import Vector

                return dialect.type_descriptor(Vector())
            except ImportError:  # pragma: no cover - postgres extra not installed
                pass
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return [float(x) for x in value]

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return [float(x) for x in value]


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


def _ts() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), default=now, nullable=False)


class ProjectRow(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    created_at: Mapped[datetime] = _ts()


class ApiKeyRow(Base):
    __tablename__ = "api_keys"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = _ts()


class RunRow(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(40), index=True)
    agent_name: Mapped[str] = mapped_column(String(64))
    task: Mapped[str] = mapped_column(Text)
    input: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), index=True)
    label: Mapped[str | None] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(24), default="live")  # live | replay | rerun | eval
    parent_run_id: Mapped[str | None] = mapped_column(String(40), index=True)
    workflow_run_id: Mapped[str | None] = mapped_column(String(40), index=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    feedback: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    steps: Mapped[int] = mapped_column(Integer, default=0)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = _ts()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_runs_project_created", "project_id", "created_at"),)


class EventRow(Base):
    __tablename__ = "events"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(40), index=True)
    run_id: Mapped[str] = mapped_column(String(40))
    seq: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(48), index=True)
    step: Mapped[int | None] = mapped_column(Integer)
    span_id: Mapped[str] = mapped_column(String(40))
    parent_span_id: Mapped[str | None] = mapped_column(String(40))
    ts: Mapped[datetime] = _ts()
    duration_ms: Mapped[float | None] = mapped_column(Float)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    __table_args__ = (UniqueConstraint("run_id", "seq", name="uq_events_run_seq"),)


class CheckpointRow(Base):
    __tablename__ = "checkpoints"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(40), index=True)
    run_id: Mapped[str] = mapped_column(String(40), index=True)
    step: Mapped[int] = mapped_column(Integer)
    event_seq: Mapped[int] = mapped_column(Integer)
    state: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = _ts()


class MemoryRow(Base):
    __tablename__ = "memories"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(40), index=True)
    lineage_id: Mapped[str] = mapped_column(String(40), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    kind: Mapped[str] = mapped_column(String(16))
    subject_key: Mapped[str | None] = mapped_column(String(200), index=True)
    content: Mapped[str] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(String(120), default="project")
    tags: Mapped[list[Any]] = mapped_column(JSON, default=list)
    source_type: Mapped[str] = mapped_column(String(32), default="manual")
    source_ref: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[str] = mapped_column(String(120), default="user")
    run_id: Mapped[str | None] = mapped_column(String(40))
    trust: Mapped[float] = mapped_column(Float, default=0.7)
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    valid_from: Mapped[datetime] = _ts()
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    status_reason: Mapped[str | None] = mapped_column(Text)
    supersedes_id: Mapped[str | None] = mapped_column(String(40))
    embedding: Mapped[list[float] | None] = mapped_column(EmbeddingType)
    retrieval_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = _ts()

    __table_args__ = (Index("ix_memories_project_status", "project_id", "status"),)


class MemoryRetrievalRow(Base):
    __tablename__ = "memory_retrievals"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(40), index=True)
    memory_id: Mapped[str] = mapped_column(String(40), index=True)
    run_id: Mapped[str | None] = mapped_column(String(40), index=True)
    receipt_id: Mapped[str | None] = mapped_column(String(40))
    query: Mapped[str] = mapped_column(Text)
    score: Mapped[float] = mapped_column(Float)
    included: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = _ts()


class PolicyRow(Base):
    __tablename__ = "policies"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(40), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    effect: Mapped[str] = mapped_column(String(24))
    tools: Mapped[list[Any]] = mapped_column(JSON, default=list)
    roles: Mapped[list[Any]] = mapped_column(JSON, default=list)
    agents: Mapped[list[Any]] = mapped_column(JSON, default=list)
    conditions: Mapped[list[Any]] = mapped_column(JSON, default=list)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    max_calls_per_run: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _ts()


class ApprovalRow(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(40), index=True)
    run_id: Mapped[str] = mapped_column(String(40), index=True)
    step: Mapped[int] = mapped_column(Integer)
    tool: Mapped[str] = mapped_column(String(120))
    args: Mapped[dict[str, Any]] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), index=True)
    requested_at: Mapped[datetime] = _ts()
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolver: Mapped[str | None] = mapped_column(String(120))
    note: Mapped[str | None] = mapped_column(Text)


class WorkflowRunRow(Base):
    __tablename__ = "workflow_runs"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(40), index=True)
    name: Mapped[str] = mapped_column(String(120))
    goal: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24))
    spec: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = _ts()
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkflowTaskRow(Base):
    __tablename__ = "workflow_tasks"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(40), index=True)
    workflow_run_id: Mapped[str] = mapped_column(String(40), index=True)
    key: Mapped[str] = mapped_column(String(64))
    agent: Mapped[str] = mapped_column(String(64))
    task: Mapped[str] = mapped_column(Text)
    depends_on: Mapped[list[Any]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2)
    run_id: Mapped[str | None] = mapped_column(String(40))
    output: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EvidenceRow(Base):
    __tablename__ = "evidence"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(40), index=True)
    workflow_run_id: Mapped[str] = mapped_column(String(40), index=True)
    run_id: Mapped[str | None] = mapped_column(String(40))
    task_key: Mapped[str | None] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = _ts()


class EvalRunRow(Base):
    __tablename__ = "eval_runs"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(40), index=True)
    suite: Mapped[str] = mapped_column(String(120))
    variant: Mapped[str] = mapped_column(String(120))
    model: Mapped[str] = mapped_column(String(120))
    seed: Mapped[int] = mapped_column(Integer, default=0)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON)
    results: Mapped[list[Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = _ts()
