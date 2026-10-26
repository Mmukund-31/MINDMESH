"""Async database wrapper (SQLite for local/offline use, PostgreSQL + pgvector in production)."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event, select, text
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

    async def create_all(self) -> None:
        async with self.engine.begin() as conn:
            if self.is_postgres:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.create_all)

    async def drop_all(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

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

    async def project_for_key(self, key: str) -> str | None:
        async with self.session() as s:
            row = (
                await s.execute(select(ApiKeyRow).where(ApiKeyRow.key_hash == hash_key(key)))
            ).scalar_one_or_none()
            return row.project_id if row else None


def _sqlite_pragmas(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA busy_timeout=30000")
    cur.close()
