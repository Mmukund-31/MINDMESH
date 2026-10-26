"""Runs against a real PostgreSQL + pgvector server (the docker-compose service, or CI's).

    docker compose up -d postgres
    MINDMESH_TEST_DATABASE_URL=postgresql://mindmesh:mindmesh@localhost:5432/mindmesh pytest -m postgres

Each test starts from an empty schema built by the Alembic migrations.
"""

import os

import httpx
import pytest
from sqlalchemy import text

from mindmesh import MindMesh
from mindmesh.core.types import MemoryCreate, MemoryUpdate
from mindmesh.demo import refund
from mindmesh.storage.db import Database, head_revision
from mindmesh.storage.vector import cosine

from ..conftest import API_KEY, OTHER_KEY, wait_for_status
from ..unit.test_migrations import schema_diff

pytestmark = pytest.mark.postgres

URL = os.environ.get("MINDMESH_TEST_DATABASE_URL", "")
V = "/api/v1"


@pytest.fixture
async def clean_db():
    if not URL.startswith("postgres"):
        pytest.skip("set MINDMESH_TEST_DATABASE_URL to a PostgreSQL URL")
    db = Database(URL)
    await db.drop_all()
    await db.dispose()
    return URL


@pytest.fixture
async def pg(clean_db):
    mm = await MindMesh(clean_db, project="pg-test").init()
    yield mm
    await mm.close()


async def test_migrations_build_the_orm_schema_with_pgvector(pg):
    assert pg.db.is_postgres
    assert await pg.db.current_revision() == head_revision()
    async with pg.db.engine.connect() as conn:
        assert await conn.run_sync(schema_diff) == []
        ext = (await conn.execute(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'"))).scalar()
        col = (await conn.execute(text(
            "SELECT udt_name FROM information_schema.columns WHERE table_name = 'memories' AND column_name = 'embedding'"
        ))).scalar()
    assert ext is not None and col == "vector"
    await pg.db.migrate()  # idempotent on an up-to-date database


async def test_pgvector_search_ranks_by_cosine_similarity(pg):
    contents = [
        "The refund window for premium customers is 30 days.",
        "Office plants are watered on Fridays.",
        "Refunds above $500 need manager approval.",
        "The cafeteria serves pasta on Tuesdays.",
    ]
    for c in contents:
        await pg.memory.add(MemoryCreate(content=c))
    query = "refund window days"
    qv = (await pg.embedder.embed([query]))[0]
    nearest = await pg.repos.memories.nearest(qv, k=4)
    # pgvector's <=> distance must agree with the reference cosine implementation
    for row, sim in nearest:
        assert sim == pytest.approx(cosine(qv, row.embedding), abs=1e-5)
    assert [s for _, s in nearest] == sorted([s for _, s in nearest], reverse=True)
    hits = await pg.memory.search(query, k=2)
    assert "refund window" in hits[0].memory.content
    v2 = await pg.memory.update(hits[0].memory.id, MemoryUpdate(content="Premium refund window is 45 days."))
    assert v2.version == 2 and (await pg.memory.get(hits[0].memory.id)).status == "superseded"


async def test_vector_search_and_listing_are_project_isolated(pg):
    other = pg.scoped(await pg.db.ensure_project("pg-other"))
    await pg.memory.add(MemoryCreate(content="Alpha secret: the launch code is 0000."))
    await other.memory.add(MemoryCreate(content="Bravo note about launch schedules."))
    qv = (await pg.embedder.embed(["launch code"]))[0]
    assert {r.content for r, _ in await other.repos.memories.nearest(qv, k=10)} == {"Bravo note about launch schedules."}
    assert all("Alpha" not in h.memory.content for h in await other.memory.search("launch code secret", k=10))
    assert [m.content for m in await other.memory.list()] == ["Bravo note about launch schedules."]


async def test_api_cross_project_isolation_on_postgres(clean_db):
    from mindmesh.server.app import create_app

    app = create_app(MindMesh(clean_db, project="alpha"), api_key=API_KEY)
    async with app.router.lifespan_context(app):
        mm = app.state.mm
        await mm.db.create_api_key(await mm.db.ensure_project("bravo"), "test", OTHER_KEY)
        await refund.seed(mm, memory_state="broken")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                     headers={"X-API-Key": API_KEY}) as api:
            assert (await api.get("/healthz")).json()["database"] == "postgresql"
            task, inp = refund.task_for("C-3310", "A-9555")
            run = (await api.post(f"{V}/runs", json={"agent": "support", "task": task, "input": inp})).json()
            await wait_for_status(api, run["id"], {"succeeded"})
            mem = (await api.get(f"{V}/memories")).json()[0]
            other = {"X-API-Key": OTHER_KEY}
            for path in (f"/runs/{run['id']}", f"/runs/{run['id']}/trace", f"/memories/{mem['id']}"):
                assert (await api.get(V + path, headers=other)).status_code == 404, path
            assert (await api.get(f"{V}/runs", headers=other)).json() == []
            assert (await api.get(f"{V}/memories/search", headers=other, params={"q": "refund policy"})).json() == []


async def test_data_survives_reconnect(clean_db):
    """A new process (fresh engine and pool) sees everything the previous one committed."""
    first = await MindMesh(clean_db, project="durable").init()
    refund.install(first)
    ids = await refund.seed(first, memory_state="broken")
    task, inp = refund.task_for("C-1042", "A-7731")
    run = await first.run("support", task, inp)
    key = await first.db.create_api_key(first.project_id, "restart")
    project_id = first.project_id
    await first.close()

    second = await MindMesh(clean_db, project="durable").init()
    try:
        assert second.project_id == project_id
        assert await second.db.project_for_key(key) == project_id
        assert (await second.repos.runs.get(run.id)).status == "succeeded"
        assert len(await second.repos.events.list(run.id)) > 0
        assert (await second.memory.get(ids["new_policy"])).scope == "agent:billing"
        qv = (await second.embedder.embed(["refund window"]))[0]
        [(row, sim)] = await second.repos.memories.nearest(qv, k=1)
        assert row.embedding and len(row.embedding) == len(qv) and sim > 0
    finally:
        await second.close()


async def test_signature_scenario_on_postgres(pg):
    refund.install(pg)
    ids = await refund.seed(pg, memory_state="broken")
    task, inp = refund.task_for("C-1042", "A-7731")
    r1 = await pg.run("support", task, inp)
    assert r1.result["answer"].startswith("DENIED")
    await pg.memory.update(ids["new_policy"], MemoryUpdate(scope="project"))
    r2 = await pg.rerun(r1.id)
    assert r2.result["answer"].startswith("APPROVED")
    assert (await pg.compare(r1.id, r2.id))["divergence_step"] == 1
