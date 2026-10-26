"""FastAPI application exposing the MindMesh control plane (``/api/v1``)."""

from __future__ import annotations

import importlib
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from ..core.errors import InvalidTransition, NotFound, ToolArgumentError
from ..sdk import MindMesh
from .routers import control, evals, memories, runs, stats, workflows

log = logging.getLogger("mindmesh.server")

DEFAULT_DEV_KEY = "mm_dev_local_key_change_me"
DEFAULT_APPS = "mindmesh.demo.refund,mindmesh.demo.research"


def install_apps(mm: MindMesh, modules: str) -> list[str]:
    """Import ``module`` paths and call their ``install(mm)`` to register tools and agents."""
    loaded = []
    for name in [m.strip() for m in modules.split(",") if m.strip()]:
        mod = importlib.import_module(name)
        mod.install(mm)
        loaded.append(name)
    return loaded


def create_app(mm: MindMesh | None = None, *, apps: str | None = None, api_key: str | None = None) -> FastAPI:
    mm = mm or MindMesh(project=os.environ.get("MINDMESH_PROJECT", "default"))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await mm.init()
        key = api_key or os.environ.get("MINDMESH_API_KEY", DEFAULT_DEV_KEY)
        await mm.db.create_api_key(mm.project_id, "bootstrap", key)
        if key == DEFAULT_DEV_KEY:
            log.warning("using the default development API key; set MINDMESH_API_KEY in production")
        app.state.apps = install_apps(mm, apps if apps is not None else os.environ.get("MINDMESH_APPS", DEFAULT_APPS))
        if os.environ.get("MINDMESH_MODEL"):
            mm.set_model_override(os.environ["MINDMESH_MODEL"])
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
    )
    app.state.mm = mm
    app.state.key_cache = {}
    app.state.eval_jobs = {}
    app.state.background = set()

    origins = os.environ.get("MINDMESH_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    app.add_middleware(
        CORSMiddleware, allow_origins=[o.strip() for o in origins if o.strip()], allow_credentials=False,
        allow_methods=["*"], allow_headers=["*"],
    )

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
        return {"status": "ok", "database": "postgresql" if mm.db.is_postgres else "sqlite",
                "apps": getattr(app.state, "apps", [])}

    for r in (runs.router, memories.router, control.router, workflows.router, evals.router, stats.router):
        app.include_router(r, prefix="/api/v1")

    studio = os.environ.get("MINDMESH_STUDIO_DIR")
    if studio and Path(studio, "index.html").exists():
        app.mount("/assets", StaticFiles(directory=Path(studio, "assets")), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):  # sync: runs in the threadpool (blocking fs access)
            f = Path(studio, path)
            if path and f.is_file() and Path(studio).resolve() in f.resolve().parents:
                return FileResponse(f)
            return FileResponse(Path(studio, "index.html"))

    return app


def main_app() -> FastAPI:
    """Uvicorn factory: ``uvicorn mindmesh.server.app:main_app --factory``."""
    return create_app()
