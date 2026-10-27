"""Alembic environment.

Programmatic use (``Database.migrate``) passes an open connection via ``config.attributes["connection"]``.
The ``alembic`` CLI (``alembic.ini`` at the repository root) connects to ``MINDMESH_DATABASE_URL``.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from mindmesh.core import aio
from mindmesh.storage.db import normalize_url
from mindmesh.storage.orm import Base

config = context.config
if config.config_file_name and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    return normalize_url(
        config.get_main_option("sqlalchemy.url") or os.environ.get("MINDMESH_DATABASE_URL", "sqlite:///mindmesh.db")
    )


def _configure(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        render_as_batch=connection.dialect.name == "sqlite",  # SQLite cannot ALTER most things in place
    )


def _run(connection: Connection) -> None:
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async(url: str) -> None:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(_run)
    finally:
        await engine.dispose()


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True,
                      dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
    else:
        aio.run(_run_async(_url()))


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
