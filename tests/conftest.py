from __future__ import annotations

import os

import httpx
import pytest

from mindmesh import MindMesh
from mindmesh.core import aio, clock

if aio.NEEDS_SELECTOR_LOOP:

    def pytest_asyncio_loop_factories(config, item):
        # psycopg's async driver cannot use Windows' default ProactorEventLoop
        return {"selector": aio.new_event_loop}


@pytest.fixture(autouse=True)
def _unfreeze_clock():
    yield
    clock.freeze(None)


@pytest.fixture
async def db_url(tmp_path) -> str:
    """A fresh SQLite file per test, or, with MINDMESH_TEST_DATABASE_URL, the shared server database reset to
    an empty schema (so the whole suite can run against PostgreSQL)."""
    url = os.environ.get("MINDMESH_TEST_DATABASE_URL")
    if not url:
        return f"sqlite:///{tmp_path / 'test.db'}"
    from mindmesh.storage.db import Database

    db = Database(url)
    await db.drop_all()
    await db.dispose()
    return url


@pytest.fixture
async def mm(db_url):
    m = await MindMesh(db_url, project="test").init()
    yield m
    await m.close()


@pytest.fixture
async def refund_mm(mm):
    from mindmesh.demo import refund

    world = refund.install(mm)
    ids = await refund.seed(mm, memory_state="broken")
    mm.test_world = world  # type: ignore[attr-defined]
    mm.test_ids = ids  # type: ignore[attr-defined]
    return mm


API_KEY = "mm_test_key_for_project_alpha_000"
OTHER_KEY = "mm_test_key_for_project_bravo_111"


@pytest.fixture
async def api(db_url):
    """HTTPX client against the real ASGI app (lifespan executed), plus a second project's key."""
    from mindmesh.server.app import create_app

    app = create_app(MindMesh(db_url, project="alpha"), api_key=API_KEY)
    async with app.router.lifespan_context(app):
        mm = app.state.mm
        other = await mm.db.ensure_project("bravo")
        await mm.db.create_api_key(other, "test", OTHER_KEY)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test",
                                     headers={"X-API-Key": API_KEY}) as client:
            client.app = app  # type: ignore[attr-defined]
            yield client


async def wait_for_status(client, run_id: str, statuses: set[str], timeout: float = 10.0) -> dict:
    import asyncio

    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        r = (await client.get(f"/api/v1/runs/{run_id}")).json()
        if r["status"] in statuses:
            return r
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError(f"run {run_id} stuck in {r['status']}")
        await asyncio.sleep(0.05)
