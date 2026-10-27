"""api key roles

``api_keys.role``: ``admin`` (full access, the default for existing keys) or ``read`` (read-only, for public demos).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Databases adopted from ``create_all`` (stamped at 0001) may already have the column.
    if "role" in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("api_keys")}:
        return
    with op.batch_alter_table("api_keys", schema=None) as batch_op:
        batch_op.add_column(sa.Column("role", sa.String(length=16), nullable=False, server_default="admin"))


def downgrade() -> None:
    with op.batch_alter_table("api_keys", schema=None) as batch_op:
        batch_op.drop_column("role")
