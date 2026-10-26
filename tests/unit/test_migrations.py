"""Alembic migrations produce exactly the ORM schema, adopt pre-migration databases and are reversible."""

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect

from mindmesh import MindMesh
from mindmesh.storage.db import Database, alembic_config, head_revision
from mindmesh.storage.orm import Base


def _ignore_embedding_type(context, inspected_column, metadata_column, inspected_type, metadata_type):
    # pgvector reflects as VECTOR while the ORM declares a dialect-switching TypeDecorator;
    # the PostgreSQL integration tests assert the column type directly.
    if metadata_column.name == "embedding":
        return False
    return None  # default comparison


def schema_diff(sync_conn) -> list:
    ctx = MigrationContext.configure(sync_conn, opts={"compare_type": _ignore_embedding_type})
    return [d for d in compare_metadata(ctx, Base.metadata)
            if not (d[0] == "remove_table" and d[1].name == "alembic_version")]


async def test_fresh_migration_matches_orm(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'm.db'}")
    try:
        await db.migrate()
        assert await db.current_revision() == head_revision()
        async with db.engine.connect() as conn:
            assert await conn.run_sync(schema_diff) == []
        await db.migrate()  # idempotent
    finally:
        await db.dispose()


async def test_pre_migration_database_is_adopted(tmp_path):
    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    legacy = Database(url)
    await legacy.create_all()  # how databases were created before Alembic
    pid = await legacy.ensure_project("old")
    await legacy.dispose()

    mm = await MindMesh(url, project="old").init()
    try:
        assert mm.project_id == pid
        assert await mm.db.current_revision() == head_revision()
    finally:
        await mm.close()


async def test_downgrade_to_base_and_back(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'd.db'}")
    try:
        await db.migrate()
        async with db.engine.begin() as conn:
            await conn.run_sync(lambda c: command.downgrade(alembic_config(c), "base"))
            assert await conn.run_sync(lambda c: inspect(c).get_table_names()) == ["alembic_version"]
        await db.migrate()
        assert await db.current_revision() == head_revision()
    finally:
        await db.dispose()


async def test_init_without_migrating_requires_current_schema(tmp_path):
    url = f"sqlite:///{tmp_path / 's.db'}"
    mm = MindMesh(url)
    try:
        try:
            await mm.init(create_schema=False)
            raise AssertionError("expected an outdated-schema error")
        except RuntimeError as e:
            assert "mindmesh db upgrade" in str(e)
        await mm.db.migrate()
        await mm.init(create_schema=False)
    finally:
        await mm.close()
