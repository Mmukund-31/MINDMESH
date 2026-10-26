"""Async database wrapper (SQLite for local/offline use, PostgreSQL + pgvector in production)."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import delete, event, inspect, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from ..core.ids import new_id
from .orm import ApiKeyRow, Base, ProjectRow


def normalize_url(url: str) -> str:
    """Accept plain ``postgresql://`` / ``sqlite:///`` URLs and pick async drivers."""
    if url.startswith("postgresql://") or url.startswith("postgres://"):
        return "postgresql+psycopg://" + url.split("://", 1)[1]
    if url.startswith("sqlite:///"):
        return "sqlite+aiosqlite:///" + url.split(":///", 1)[1]
    return url


MIGRATIONS_DIR = Path(__file__).parent / "migrations"
INITIAL_REVISION = "0001"
_MIGRATION_LOCK = 0x6D696E646D657368  # pg advisory lock id ("mindmesh"): one migrator at a time


def alembic_config(connection: Connection | None = None):
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.attributes["connection"] = connection
    cfg.attributes["configure_logger"] = False
    return cfg


def head_revision() -> str:
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


class Database:
    def __init__(self, url: str = "sqlite+aiosqlite:///mindmesh.db", *, echo: bool = False):
        self.url = normalize_url(url)
        kwargs: dict = {"echo": echo}
        if self.is_sqlite:
            kwargs["connect_args"] = {"timeout": 30}
        self.engine: AsyncEngine = create_async_engine(self.url, **kwargs)
        if self.is_sqlite:
            event.listen(self.engine.sync_engine, "connect", _sqlite_pragmas)
        self._sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    @property
    def is_sqlite(self) -> bool:
        return self.url.startswith("sqlite")

    @property
    def is_postgres(self) -> bool:
        return self.url.startswith("postgresql")

    async def migrate(self, revision: str = "head") -> None:
        """Apply Alembic migrations up to ``revision``.

        Databases created by ``create_all`` before migrations existed are adopted by stamping the
        initial revision first. On PostgreSQL an advisory lock serialises concurrent migrators
        (e.g. several API replicas starting at once).
        """
        async with self.engine.begin() as conn:
            if self.is_postgres:
                await conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _MIGRATION_LOCK})
            await conn.run_sync(_upgrade, revision)

    async def current_revision(self) -> str | None:
        async with self.engine.connect() as conn:
            return await conn.run_sync(_current_revision)

    async def require_current_schema(self) -> None:
        current, head = await self.current_revision(), head_revision()
        if current != head:
            raise RuntimeError(f"database schema is at revision {current!r}, expected {head!r}; "
                               "run `mindmesh db upgrade`")

    async def create_all(self) -> None:
        """Create tables directly from the ORM, bypassing migrations (scratch databases only)."""
        async with self.engine.begin() as conn:
            if self.is_postgres:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.create_all)

    async def drop_all(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))

    async def ping(self) -> None:
        async with self.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self._sessions() as s:
            try:
                yield s
                await s.commit()
            except BaseException:
                await s.rollback()
                raise

    async def dispose(self) -> None:
        await self.engine.dispose()

    # ----------------------------------------------------------------- projects / keys

    async def ensure_project(self, name: str) -> str:
        async with self.session() as s:
            row = (await s.execute(select(ProjectRow).where(ProjectRow.name == name))).scalar_one_or_none()
            if row:
                return row.id
            pid = new_id("prj")
            s.add(ProjectRow(id=pid, name=name))
            return pid

    async def list_projects(self) -> list[ProjectRow]:
        async with self.session() as s:
            return list((await s.execute(select(ProjectRow).order_by(ProjectRow.created_at))).scalars())

    async def create_api_key(self, project_id: str, name: str = "default", key: str | None = None) -> str:
        """Create (or idempotently register) an API key. Only the SHA-256 hash is stored."""
        key = key or "mm_" + secrets.token_urlsafe(24)
        h = hash_key(key)
        async with self.session() as s:
            existing = (await s.execute(select(ApiKeyRow).where(ApiKeyRow.key_hash == h))).scalar_one_or_none()
            if existing is None:
                s.add(ApiKeyRow(id=new_id("key"), project_id=project_id, name=name, key_hash=h))
            elif existing.project_id != project_id:
                raise ValueError("API key already bound to another project")
        return key

    async def set_bootstrap_key(self, project_id: str, key: str) -> None:
        """Register the server's configured key and revoke any previous one, so rotating
        ``MINDMESH_API_KEY`` invalidates the old value."""
        await self.create_api_key(project_id, "bootstrap", key)
        async with self.session() as s:
            await s.execute(delete(ApiKeyRow).where(ApiKeyRow.project_id == project_id, ApiKeyRow.name == "bootstrap",
                                                    ApiKeyRow.key_hash != hash_key(key)))

    async def revoke_api_key(self, key: str) -> bool:
        async with self.session() as s:
            res = await s.execute(delete(ApiKeyRow).where(ApiKeyRow.key_hash == hash_key(key)))
            return res.rowcount > 0

    async def project_for_key(self, key: str) -> str | None:
        async with self.session() as s:
            row = (
                await s.execute(select(ApiKeyRow).where(ApiKeyRow.key_hash == hash_key(key)))
            ).scalar_one_or_none()
            return row.project_id if row else None


def _upgrade(conn: Connection, revision: str) -> None:
    from alembic import command

    cfg = alembic_config(conn)
    tables = set(inspect(conn).get_table_names())
    if "projects" in tables and "alembic_version" not in tables:
        command.stamp(cfg, INITIAL_REVISION)
    command.upgrade(cfg, revision)


def _current_revision(conn: Connection) -> str | None:
    from alembic.runtime.migration import MigrationContext

    return MigrationContext.configure(conn).get_current_revision()


def _sqlite_pragmas(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA busy_timeout=30000")
    cur.close()
