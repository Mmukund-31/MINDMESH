"""Runs against the docker-compose PostgreSQL + pgvector service.

    docker compose up -d postgres
    MINDMESH_TEST_DATABASE_URL=postgresql://mindmesh:mindmesh@localhost:5432/mindmesh pytest -m postgres
"""

import os

import pytest

from mindmesh import MindMesh
from mindmesh.core.types import MemoryCreate, MemoryUpdate
from mindmesh.demo import refund

pytestmark = pytest.mark.postgres

URL = os.environ.get("MINDMESH_TEST_DATABASE_URL", "")


@pytest.fixture
async def pg():
    if not URL.startswith("postgres"):
        pytest.skip("set MINDMESH_TEST_DATABASE_URL to a PostgreSQL URL")
    mm = MindMesh(URL, project="pg-test")
    await mm.db.drop_all()
    await mm.init()
    yield mm
    await mm.close()


async def test_pgvector_search_and_lifecycle(pg):
    await pg.memory.add(MemoryCreate(content="The refund window for premium customers is 30 days.", subject_key="w"))
    await pg.memory.add(MemoryCreate(content="Office plants are watered on Fridays."))
    hits = await pg.memory.search("refund window days", k=2)
    assert "refund" in hits[0].memory.content
    v2 = await pg.memory.update(hits[0].memory.id, MemoryUpdate(content="Premium refund window is 45 days."))
    assert v2.version == 2


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
