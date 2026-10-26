"""initial schema

All tenant-owned tables carry ``project_id``. On PostgreSQL, ``memories.embedding`` is a pgvector
``vector`` column (dimensionless, so models with different embedding sizes can coexist); elsewhere it is JSON.

Revision ID: 0001
Revises:
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _embedding_type() -> sa.types.TypeEngine:
    if op.get_bind().dialect.name == "postgresql":
        from pgvector.sqlalchemy import Vector

        return Vector()
    return sa.JSON()


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "approvals",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("run_id", sa.String(length=40), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("tool", sa.String(length=120), nullable=False),
        sa.Column("args", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolver", sa.String(length=120), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("approvals", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_approvals_project_id"), ["project_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_approvals_run_id"), ["run_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_approvals_status"), ["status"], unique=False)

    op.create_table(
        "checkpoints",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("run_id", sa.String(length=40), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("event_seq", sa.Integer(), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("checkpoints", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_checkpoints_project_id"), ["project_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_checkpoints_run_id"), ["run_id"], unique=False)

    op.create_table(
        "eval_runs",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("suite", sa.String(length=120), nullable=False),
        sa.Column("variant", sa.String(length=120), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("eval_runs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_eval_runs_project_id"), ["project_id"], unique=False)

    op.create_table(
        "events",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("run_id", sa.String(length=40), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=48), nullable=False),
        sa.Column("step", sa.Integer(), nullable=True),
        sa.Column("span_id", sa.String(length=40), nullable=False),
        sa.Column("parent_span_id", sa.String(length=40), nullable=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "seq", name="uq_events_run_seq"),
    )
    with op.batch_alter_table("events", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_events_project_id"), ["project_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_events_type"), ["type"], unique=False)

    op.create_table(
        "evidence",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("workflow_run_id", sa.String(length=40), nullable=False),
        sa.Column("run_id", sa.String(length=40), nullable=True),
        sa.Column("task_key", sa.String(length=64), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=500), nullable=True),
        sa.Column("created_by", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("evidence", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_evidence_project_id"), ["project_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_evidence_workflow_run_id"), ["workflow_run_id"], unique=False)

    op.create_table(
        "memories",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("lineage_id", sa.String(length=40), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("subject_key", sa.String(length=200), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("scope", sa.String(length=120), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_ref", sa.String(length=500), nullable=True),
        sa.Column("created_by", sa.String(length=120), nullable=False),
        sa.Column("run_id", sa.String(length=40), nullable=True),
        sa.Column("trust", sa.Float(), nullable=False),
        sa.Column("importance", sa.Float(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.Column("supersedes_id", sa.String(length=40), nullable=True),
        sa.Column("embedding", _embedding_type(), nullable=True),
        sa.Column("retrieval_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("memories", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_memories_lineage_id"), ["lineage_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_memories_project_id"), ["project_id"], unique=False)
        batch_op.create_index("ix_memories_project_status", ["project_id", "status"], unique=False)
        batch_op.create_index(batch_op.f("ix_memories_status"), ["status"], unique=False)
        batch_op.create_index(batch_op.f("ix_memories_subject_key"), ["subject_key"], unique=False)

    op.create_table(
        "memory_retrievals",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("memory_id", sa.String(length=40), nullable=False),
        sa.Column("run_id", sa.String(length=40), nullable=True),
        sa.Column("receipt_id", sa.String(length=40), nullable=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("included", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("memory_retrievals", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_memory_retrievals_memory_id"), ["memory_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_memory_retrievals_project_id"), ["project_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_memory_retrievals_run_id"), ["run_id"], unique=False)

    op.create_table(
        "policies",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("effect", sa.String(length=24), nullable=False),
        sa.Column("tools", sa.JSON(), nullable=False),
        sa.Column("roles", sa.JSON(), nullable=False),
        sa.Column("agents", sa.JSON(), nullable=False),
        sa.Column("conditions", sa.JSON(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("max_calls_per_run", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("policies", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_policies_project_id"), ["project_id"], unique=False)

    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "runs",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("agent_name", sa.String(length=64), nullable=False),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("input", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("parent_run_id", sa.String(length=40), nullable=True),
        sa.Column("workflow_run_id", sa.String(length=40), nullable=True),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("feedback", sa.JSON(), nullable=True),
        sa.Column("steps", sa.Integer(), nullable=False),
        sa.Column("tool_calls", sa.Integer(), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_runs_parent_run_id"), ["parent_run_id"], unique=False)
        batch_op.create_index("ix_runs_project_created", ["project_id", "created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_runs_project_id"), ["project_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_runs_status"), ["status"], unique=False)
        batch_op.create_index(batch_op.f("ix_runs_workflow_run_id"), ["workflow_run_id"], unique=False)

    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("spec", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("workflow_runs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_workflow_runs_project_id"), ["project_id"], unique=False)

    op.create_table(
        "workflow_tasks",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("workflow_run_id", sa.String(length=40), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("agent", sa.String(length=64), nullable=False),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("depends_on", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(length=40), nullable=True),
        sa.Column("output", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("workflow_tasks", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_workflow_tasks_project_id"), ["project_id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_workflow_tasks_workflow_run_id"), ["workflow_run_id"], unique=False
        )

    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_hash"),
    )
    with op.batch_alter_table("api_keys", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_api_keys_project_id"), ["project_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("api_keys", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_api_keys_project_id"))

    op.drop_table("api_keys")
    with op.batch_alter_table("workflow_tasks", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_workflow_tasks_workflow_run_id"))
        batch_op.drop_index(batch_op.f("ix_workflow_tasks_project_id"))

    op.drop_table("workflow_tasks")
    with op.batch_alter_table("workflow_runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_workflow_runs_project_id"))

    op.drop_table("workflow_runs")
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_runs_workflow_run_id"))
        batch_op.drop_index(batch_op.f("ix_runs_status"))
        batch_op.drop_index(batch_op.f("ix_runs_project_id"))
        batch_op.drop_index("ix_runs_project_created")
        batch_op.drop_index(batch_op.f("ix_runs_parent_run_id"))

    op.drop_table("runs")
    op.drop_table("projects")
    with op.batch_alter_table("policies", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_policies_project_id"))

    op.drop_table("policies")
    with op.batch_alter_table("memory_retrievals", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_memory_retrievals_run_id"))
        batch_op.drop_index(batch_op.f("ix_memory_retrievals_project_id"))
        batch_op.drop_index(batch_op.f("ix_memory_retrievals_memory_id"))

    op.drop_table("memory_retrievals")
    with op.batch_alter_table("memories", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_memories_subject_key"))
        batch_op.drop_index(batch_op.f("ix_memories_status"))
        batch_op.drop_index("ix_memories_project_status")
        batch_op.drop_index(batch_op.f("ix_memories_project_id"))
        batch_op.drop_index(batch_op.f("ix_memories_lineage_id"))

    op.drop_table("memories")
    with op.batch_alter_table("evidence", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_evidence_workflow_run_id"))
        batch_op.drop_index(batch_op.f("ix_evidence_project_id"))

    op.drop_table("evidence")
    with op.batch_alter_table("events", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_events_type"))
        batch_op.drop_index(batch_op.f("ix_events_project_id"))

    op.drop_table("events")
    with op.batch_alter_table("eval_runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_eval_runs_project_id"))

    op.drop_table("eval_runs")
    with op.batch_alter_table("checkpoints", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_checkpoints_run_id"))
        batch_op.drop_index(batch_op.f("ix_checkpoints_project_id"))

    op.drop_table("checkpoints")
    with op.batch_alter_table("approvals", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_approvals_status"))
        batch_op.drop_index(batch_op.f("ix_approvals_run_id"))
        batch_op.drop_index(batch_op.f("ix_approvals_project_id"))

    op.drop_table("approvals")
