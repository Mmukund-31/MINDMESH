"""audit log

``audit_log``: changes made through the API (policies, approvals, memories, keys), attributed to the API key.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if "audit_log" in sa.inspect(op.get_bind()).get_table_names():  # adopted from create_all
        return
    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("actor", sa.String(length=120), nullable=False),
        sa.Column("action", sa.String(length=48), nullable=False),
        sa.Column("target_type", sa.String(length=24), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("audit_log", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_audit_log_project_id"), ["project_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_audit_log_action"), ["action"], unique=False)
        batch_op.create_index("ix_audit_project_created", ["project_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_table("audit_log")
