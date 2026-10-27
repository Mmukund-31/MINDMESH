"""FastAPI application exposing the MindMesh control plane (``/api/v1``)."""

from __future__ import annotations

import importlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from ..config import DEFAULT_DEV_KEY, Settings
from ..core.errors import InvalidTransition, NotFound, ToolArgumentError
from ..sdk import MindMesh
from .deps import KeyCache
from .ratelimit import RateLimitMiddleware
from .routers import control, evals, experiments, memories, runs, stats, workflows
from .security import SecurityMiddleware

log = logging.getLogger("mindmesh.server")


def install_apps(mm: MindMesh, modules: str) -> list[str]:
    """Import ``module`` paths and call their ``install(mm)`` to register tools and agents."""
    loaded = []
    for name in [m.strip() for m in modules.split(",") if m.strip()]:
        mod = importlib.import_module(name)
        mod.install(mm)
        loaded.append(name)
    return loaded


def create_app(
    mm: MindMesh | None = None,
    *,
    apps: str | None = None,
    api_key: str | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    if api_key is not None:
        settings.api_key = api_key
    if mm is not None:
        settings.database_url, settings.database_url_set = mm.db.url, True
    warnings = settings.validate()  # raises ConfigError on unsafe production settings
    mm = mm or MindMesh(settings.database_url, project=settings.project)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.auto_migrate:
            await mm.init()
        else:
            await mm.init(create_schema=False)
        key = settings.resolved_api_key()
        await mm.db.set_bootstrap_key(mm.project_id, key)
        if key == DEFAULT_DEV_KEY:
            log.warning("using the public development API key; set MINDMESH_API_KEY (MINDMESH_ENV=production "
                        "refuses to start without one)")
        if warnings:
            log.info("development mode; production would reject: %s", "; ".join(warnings))
        app.state.apps = install_apps(mm, apps if apps is not None else settings.apps)
        if settings.model:
            mm.set_model_override(settings.model)
        if settings.public_key:
            await _setup_public_demo(mm, settings, app.state.apps)
        yield
        for t in list(app.state.background):
            t.cancel()
        await mm.close()

    app = FastAPI(
        title="MINDMESH API",
        version="0.1.0",
        description="Reliability and control plane for AI agents: memory, context, policies, orchestration, "
        "tracing, replay and evaluation.",
        lifespan=lifespan,
        docs_url="/docs" if settings.docs else None,
        redoc_url="/redoc" if settings.docs else None,
        openapi_url="/openapi.json" if settings.docs else None,
    )
    app.state.mm = mm
    app.state.settings = settings
    app.state.key_cache = KeyCache()
    app.state.eval_jobs = {}
    app.state.background = set()

    # Inside CORS, so 429 responses still carry CORS headers and browsers can read them.
    app.add_middleware(RateLimitMiddleware, per_minute=settings.rate_limit,
                       writes_per_minute=settings.rate_limit_writes, client_ip_header=settings.client_ip_header)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["X-API-Key", "Authorization", "Content-Type", "Last-Event-ID"],
        max_age=600,
    )
    app.add_middleware(SecurityMiddleware, max_body_bytes=settings.max_body_bytes)

    @app.exception_handler(NotFound)
    async def _nf(_: Request, exc: NotFound):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(InvalidTransition)
    async def _it(_: Request, exc: InvalidTransition):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(ToolArgumentError)
    async def _ta(_: Request, exc: ToolArgumentError):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(ValidationError)
    async def _ve(_: Request, exc: ValidationError):
        return JSONResponse({"detail": exc.errors(include_url=False, include_context=False)}, status_code=422)

    @app.exception_handler(ValueError)
    async def _v(_: Request, exc: ValueError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.get("/healthz", tags=["meta"])
    async def healthz():
        try:
            await mm.db.ping()
        except Exception:  # noqa: BLE001 - report unhealthy instead of a 500
            log.exception("health check: database unreachable")
            return JSONResponse({"status": "unavailable", "database": "unreachable"}, status_code=503)
        return {"status": "ok", "database": "postgresql" if mm.db.is_postgres else "sqlite"}

    for r in (runs.router, memories.router, control.router, workflows.router, evals.router, stats.router,
              experiments.router):
        app.include_router(r, prefix="/api/v1")

    studio = settings.studio_dir
    if studio and Path(studio, "index.html").exists():
        app.mount("/assets", StaticFiles(directory=Path(studio, "assets")), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):  # sync: runs in the threadpool (blocking fs access)
            f = Path(studio, path)
            if path and f.is_file() and Path(studio).resolve() in f.resolve().parents:
                return FileResponse(f)
            return FileResponse(Path(studio, "index.html"))

    return app


async def _setup_public_demo(mm: MindMesh, settings: Settings, apps: list[str]) -> None:
    """Bind the read-only public key to its own project, seeding the showcase there on first boot."""
    from ..demo import showcase

    project_id = await mm.db.ensure_project(settings.public_project)
    await mm.db.set_bootstrap_key(project_id, settings.public_key, name="public", role="read")
    demo = mm.scoped(project_id)
    showcase_apps = {"mindmesh.demo.refund", "mindmesh.demo.research"}
    if settings.seed_public and showcase_apps <= set(apps) and await showcase.is_empty(demo):
        log.info("seeding the public demo project %r", settings.public_project)
        await showcase.seed(demo)


def main_app() -> FastAPI:
    """Uvicorn factory: ``uvicorn mindmesh.server.app:main_app --factory``."""
    return create_app()
