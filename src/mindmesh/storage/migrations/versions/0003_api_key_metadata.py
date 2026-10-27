"""api key metadata

``api_keys.prefix`` (first characters of the key, to tell keys apart in listings; unknown for older keys) and
``api_keys.last_used_at``.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Databases adopted from ``create_all`` (stamped at 0001) may already have the columns.
    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("api_keys")}
    with op.batch_alter_table("api_keys", schema=None) as batch_op:
        if "prefix" not in existing:
            batch_op.add_column(sa.Column("prefix", sa.String(length=16), nullable=True))
        if "last_used_at" not in existing:
            batch_op.add_column(sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("api_keys", schema=None) as batch_op:
        batch_op.drop_column("last_used_at")
        batch_op.drop_column("prefix")
