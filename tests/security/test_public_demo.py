"""Deployment safety: read-only public demo keys, the separate demo project, and rate limiting."""

import httpx
import pytest

from mindmesh import MindMesh
from mindmesh.config import ConfigError, Settings
from mindmesh.server.app import create_app
from mindmesh.server.ratelimit import RateLimitMiddleware

from ..conftest import API_KEY

V = "/api/v1"
PUBLIC_KEY = "mm_public_demo_read_only_key_0000"


@pytest.fixture
async def public_api(db_url):
    settings = Settings(public_key=PUBLIC_KEY, seed_public=True, rate_limit=0, rate_limit_writes=0,
                        cors_origins=["https://studio.example"])
    app = create_app(MindMesh(db_url, project="alpha"), api_key=API_KEY, settings=settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test",
                                     headers={"X-API-Key": PUBLIC_KEY}) as client:
            client.app = app  # type: ignore[attr-defined]
            yield client


async def test_public_key_reads_a_separate_seeded_project(public_api):
    me = (await public_api.get(f"{V}/me")).json()
    assert me["project_name"] == "demo" and me["role"] == "read"
    runs = (await public_api.get(f"{V}/runs")).json()
    assert len(runs) >= 5 and (await public_api.get(f"{V}/memories")).json()
    admin = {"X-API-Key": API_KEY}
    assert (await public_api.get(f"{V}/me", headers=admin)).json()["role"] == "admin"
    assert (await public_api.get(f"{V}/runs", headers=admin)).json() == []  # the developer project is untouched


async def test_public_key_cannot_write_but_can_preview_and_stream(public_api):
    run = (await public_api.get(f"{V}/runs")).json()[0]
    mem = (await public_api.get(f"{V}/memories")).json()[0]
    writes = [
        public_api.post(f"{V}/runs", json={"agent": "support", "task": "x"}),
        public_api.post(f"{V}/runs/{run['id']}/rerun", json={}),
        public_api.patch(f"{V}/memories/{mem['id']}", json={"content": "pwned"}),
        public_api.post(f"{V}/memories/{mem['id']}/retract", json={"reason": "x", "by": "x"}),
        public_api.put(f"{V}/policies/yaml", json={"yaml": "rules: []"}),
        public_api.post(f"{V}/experiments/refund/reset"),
    ]
    for req in writes:
        r = await req
        assert r.status_code == 403 and "read-only" in r.json()["detail"], r.request.url
    assert (await public_api.get(f"{V}/memories/{mem['id']}")).json()["content"] == mem["content"]

    assert (await public_api.post(f"{V}/runs/{run['id']}/stream-token")).status_code == 200
    preview = await public_api.post(f"{V}/context/preview", json={"query": "refund policy", "agent": "support"})
    assert preview.status_code == 200
    impact = await public_api.post(f"{V}/memories/{mem['id']}/impact", json={"change": {"scope": "project"}})
    assert impact.status_code == 200


async def test_seeding_happens_once(db_url):
    settings = Settings(public_key=PUBLIC_KEY, seed_public=True)
    counts = []
    for _ in range(2):  # a restart must not reseed (or duplicate) the demo
        app = create_app(MindMesh(db_url, project="alpha"), api_key=API_KEY, settings=settings)
        async with app.router.lifespan_context(app):
            demo = app.state.mm.scoped(await app.state.mm.db.ensure_project("demo"))
            counts.append(len(await demo.repos.runs.list(limit=500)))
    assert counts[0] >= 5 and counts[0] == counts[1]


@pytest.mark.parametrize("kwargs, msg", [
    ({"api_key": PUBLIC_KEY}, "differ from MINDMESH_API_KEY"),
    ({"public_project": "default"}, "differ from MINDMESH_PROJECT"),
    ({"public_key": "short"}, "at least 16"),
    ({"rate_limit": -1}, ">= 0"),
])
def test_public_demo_config_is_validated(kwargs, msg):
    with pytest.raises(ConfigError, match=msg):
        Settings(**{"public_key": PUBLIC_KEY, **kwargs}).validate()


async def test_rate_limit_returns_429_with_retry_after_and_cors(db_url):
    settings = Settings(rate_limit=5, rate_limit_writes=2, cors_origins=["https://studio.example"])
    app = create_app(MindMesh(db_url, project="alpha"), api_key=API_KEY, settings=settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, client=("203.0.113.7", 1234))
        headers = {"X-API-Key": API_KEY, "Origin": "https://studio.example"}
        async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=headers) as c:
            codes = [(await c.get(f"{V}/runs")).status_code for _ in range(6)]
            assert codes == [200] * 5 + [429]
            r = await c.get(f"{V}/runs")
            assert int(r.headers["retry-after"]) >= 1
            assert r.headers["access-control-allow-origin"] == "https://studio.example"
            assert (await c.get("/healthz")).status_code == 200  # health checks are never limited
        other = httpx.ASGITransport(app=app, client=("198.51.100.9", 1234))
        async with httpx.AsyncClient(transport=other, base_url="http://test", headers=headers) as c:
            assert (await c.get(f"{V}/runs")).status_code == 200  # buckets are per client


async def test_write_bucket_is_stricter_and_refills():
    now = [0.0]
    calls = []

    async def app(scope, receive, send):
        calls.append(scope["method"])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    mw = RateLimitMiddleware(app, per_minute=100, writes_per_minute=2, clock=lambda: now[0])
    sent = []

    async def send(message):
        if message["type"] == "http.response.start":
            sent.append(message["status"])

    def scope(method):
        return {"type": "http", "path": f"{V}/runs", "method": method, "client": ("192.0.2.1", 1)}

    for _ in range(3):
        await mw(scope("POST"), None, send)
    await mw(scope("GET"), None, send)
    assert sent == [200, 200, 429, 200]
    now[0] += 30  # 2/min refills one token every 30 s
    await mw(scope("POST"), None, send)
    assert sent[-1] == 200


async def test_client_ip_header_identifies_clients_behind_a_proxy():
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    mw = RateLimitMiddleware(app, per_minute=1, writes_per_minute=0, client_ip_header="True-Client-IP")
    sent = []

    async def send(message):
        if message["type"] == "http.response.start":
            sent.append(message["status"])

    def scope(ip):  # every request arrives from the same proxy address
        return {"type": "http", "path": f"{V}/runs", "method": "GET", "client": ("10.0.0.1", 1),
                "headers": [(b"x-forwarded-for", b"6.6.6.6"), (b"true-client-ip", ip.encode())]}

    for ip in ("192.0.2.1", "192.0.2.2", "192.0.2.1"):
        await mw(scope(ip), None, send)
    assert sent == [200, 200, 429]
