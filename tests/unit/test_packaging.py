"""The installable package ships a current Studio build and serves it in development."""

import runpy
from pathlib import Path

import httpx

from mindmesh import MindMesh
from mindmesh.config import Settings
from mindmesh.server.app import PACKAGED_STUDIO, create_app

ROOT = Path(__file__).resolve().parents[2]


def test_bundled_studio_matches_the_studio_sources():
    build = runpy.run_path(str(ROOT / "scripts" / "build_studio.py"))
    assert build["check"]() == 0, "run: python scripts/build_studio.py"


async def test_development_server_serves_the_bundled_studio(db_url):
    app = create_app(MindMesh(db_url, project="p"), settings=Settings())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            for path in ("/", "/runs/run_x", "/settings"):  # SPA routes fall back to index.html
                r = await c.get(path)
                assert r.status_code == 200 and "<div id=\"root\">" in r.text, path
            asset = next((PACKAGED_STUDIO / "assets").glob("index-*.js")).name
            assert (await c.get(f"/assets/{asset}")).status_code == 200
            assert (await c.get("/api/v1/runs")).status_code == 401  # API routes are not shadowed


def test_production_does_not_serve_the_bundled_studio():
    def serves_spa(app):
        return any(getattr(r, "path", "") == "/{path:path}" for r in app.routes)

    prod = Settings(env="production", api_key="k" * 32, secret_key="s" * 32, database_url_set=True,
                    database_url="postgresql://x@y/z")
    assert serves_spa(create_app(MindMesh("sqlite:///:memory:", project="p"), settings=Settings()))
    assert not serves_spa(create_app(settings=prod))  # production Studio is deployed separately
