"""``mindmesh`` command line: serve the API, run the signature demo, seed data, run benchmarks."""

from __future__ import annotations

import os
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .core import aio

app = typer.Typer(help="MINDMESH: reliability and control plane for AI agents.", no_args_is_help=True)
demo_app = typer.Typer(help="Signature demonstrations.", no_args_is_help=True)
app.add_typer(demo_app, name="demo")
db_app = typer.Typer(help="Database schema migrations (Alembic).", no_args_is_help=True)
app.add_typer(db_app, name="db")
console = Console()


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind address"),
    port: int = typer.Option(8000, help="Port"),
    reload: bool = typer.Option(False, help="Auto-reload on code changes"),
):
    """Run the MindMesh API server (Studio talks to it)."""
    import uvicorn

    from .config import ConfigError, Settings

    try:
        Settings.from_env().validate()
    except ConfigError as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(2) from e
    uvicorn.run("mindmesh.server.app:main_app", factory=True, host=host, port=port, reload=reload,
                loop=aio.uvicorn_loop())


def _mm(database_url: str | None, project: str):
    from .sdk import MindMesh

    return MindMesh(database_url, project=project)


def _print_receipt(payload: dict) -> None:
    t = Table(title=f"Context receipt · step {payload['step']} · {payload['used_tokens']}/{payload['budget_tokens']} tokens",
              show_lines=False)
    t.add_column("", width=3)
    t.add_column("subject")
    t.add_column("scope")
    t.add_column("score", justify="right")
    t.add_column("reason / content")
    for i in payload["included"]:
        if i["kind"] == "task":
            continue
        t.add_row("[green]✔[/]", i.get("subject_key") or i["kind"], i.get("scope") or "", f"{i['score']['total']:.2f}",
                  i["content"][:70])
    for i in payload["excluded"]:
        t.add_row("[red]✘[/]", i.get("subject_key") or i["kind"], i.get("scope") or "", f"{i['score']['total']:.2f}",
                  f"[yellow]{i['reason']}[/] {i.get('detail') or ''}"[:90])
    console.print(t)


@demo_app.command("refund")
def demo_refund(
    database_url: str = typer.Option(None, envvar="MINDMESH_DATABASE_URL", help="Defaults to sqlite:///mindmesh.db"),
    project: str = typer.Option("default", envvar="MINDMESH_PROJECT"),
    model: str = typer.Option(None, envvar="MINDMESH_MODEL", help="e.g. ollama:qwen3:8b (default: scripted brain)"),
    fresh: bool = typer.Option(True, help="Clear this project's memories/policies first"),
):
    """Fail -> diagnose (trace + context receipt) -> fix memory -> rerun -> compare -> benchmark."""
    aio.run(_demo_refund(database_url, project, model, fresh))


async def _demo_refund(database_url, project, model, fresh):
    from .core.types import MemoryUpdate, RunFeedback
    from .demo import refund
    from .eval.report import METRIC_ROWS, fmt
    from .eval.runner import run_suite
    from .eval.suite import load_suite

    mm = await _mm(database_url, project).init()
    try:
        if model:
            mm.set_model_override(model)
        refund.install(mm)
        if fresh:
            await _reset_project(mm)
        ids = await refund.seed(mm, memory_state="broken")
        console.print(Panel.fit("[bold]1 · Run[/] the support agent on a valid premium refund (C-1042 / A-7731)"))
        task, inp = refund.task_for("C-1042", "A-7731")
        r1 = await mm.run("support", task, inp, label="demo: original")
        console.print(f"run {r1.id}: [bold]{r1.status}[/] → {(r1.result or {}).get('answer') or r1.error}")
        await mm.repos.runs.update(r1.id, feedback=RunFeedback(
            verdict="incorrect", note="Customer is premium (30-day window); refund should have been approved.",
            by="support-lead").model_dump())
        console.print("[red]✘ Customer complaint: premium customers have a 30-day window. The decision is wrong.[/]")

        console.print(Panel.fit("[bold]2 · Diagnose[/] with the execution trace and the context receipt"))
        for e in await mm.repos.events.list(r1.id, types=["step.finished"]):
            a = e.payload["action"]
            label = a.get("tool") or "final_answer"
            console.print(f"  step {e.step}: {label} {a.get('args') or ''} → {e.payload['outcome'].get('status')}")
        receipts = await mm.repos.events.list(r1.id, types=["context.assembled"])
        _print_receipt(receipts[-1].payload)
        console.print("[yellow]Root cause:[/] the updated policy exists but lives in scope [bold]agent:billing[/], "
                      "so it was excluded (scope_mismatch); the stale 14-day policy was used.")

        console.print(Panel.fit("[bold]3 · Fix[/] promote the updated policy to project scope (new version supersedes the stale fact)"))
        fixed = await mm.memory.update(ids["new_policy"], MemoryUpdate(
            scope="project", reason="policy applies to all customer-facing agents", edited_by="support-lead"))
        console.print(f"memory {fixed.id} v{fixed.version} scope={fixed.scope}; "
                      f"old policy now: {(await mm.memory.get(ids['old_policy'])).status}")

        console.print(Panel.fit("[bold]4 · Rerun[/] the same task and compare"))
        r2 = await mm.rerun(r1.id)
        console.print(f"run {r2.id}: [bold]{r2.status}[/] → {(r2.result or {}).get('answer') or r2.error}")
        cmp = await mm.compare(r1.id, r2.id)
        added = {m: cmp["memories"].get(m, {}) for s in cmp["steps"] for m in s["context_added"]}
        labels = [f"{v.get('subject_key')} ({v.get('scope')})" for v in added.values()]
        console.print(f"diverged at step {cmp['divergence_step']}; context now includes: {labels}")
        rp = await mm.replay(r1.id)
        console.print(f"safe replay of original (no tools/models executed): {rp.status} → "
                      f"{(rp.result or {}).get('answer', '')[:60]}")

        console.print(Panel.fit("[bold]5 · Measure[/] baseline vs misconfigured vs fixed on the refund suite"))
        report = await run_suite(load_suite("refund"), model=model, store=mm, results_dir=Path("bench/results"))
        t = Table()
        t.add_column("metric")
        for n in report["variants"]:
            t.add_column(n, justify="right")
        for key, label, kind in METRIC_ROWS:
            t.add_row(label, *[fmt(v["metrics"].get(key), kind) for v in report["variants"].values()])
        console.print(t)
        console.print(f"report: {report['files']['markdown']}")
    finally:
        await mm.close()


async def _reset_project(mm) -> None:
    from sqlalchemy import delete

    from .storage.orm import MemoryRetrievalRow, MemoryRow, PolicyRow

    async with mm.db.session() as s:
        for tbl in (MemoryRow, MemoryRetrievalRow, PolicyRow):
            await s.execute(delete(tbl).where(tbl.project_id == mm.project_id))


@demo_app.command("seed")
def demo_seed(
    database_url: str = typer.Option(None, envvar="MINDMESH_DATABASE_URL"),
    project: str = typer.Option("default", envvar="MINDMESH_PROJECT"),
    model: str = typer.Option(None, envvar="MINDMESH_MODEL"),
):
    """Seed the broken refund scenario + a few runs and a workflow so Studio has data to explore."""
    aio.run(_seed(database_url, project, model))


async def _seed(database_url, project, model):
    from .core.types import RunFeedback
    from .demo import refund, research

    mm = await _mm(database_url, project).init()
    try:
        if model:
            mm.set_model_override(model)
        refund.install(mm)
        research.install(mm)
        await _reset_project(mm)
        await refund.seed(mm, memory_state="broken")
        cases = [("C-1042", "A-7731"), ("C-2077", "A-8812"), ("C-2077", "A-6666"), ("C-3310", "A-9555"),
                 ("C-2077", "A-9020")]
        for cid, oid in cases:
            task, inp = refund.task_for(cid, oid)
            r = await mm.run("support", task, inp)
            if oid == "A-7731":
                await mm.repos.runs.update(r.id, feedback=RunFeedback(
                    verdict="incorrect", note="Premium customer within 30 days — should be approved.",
                    by="support-lead").model_dump())
            console.print(f"{oid}: {r.status} {(r.result or {}).get('answer', '')[:80]}")
        research.reset_faults()
        await mm.run_workflow(research.TEMPLATE)
        console.print("[green]seeded.[/] Start the API with `mindmesh serve` and open Studio.")
    finally:
        await mm.close()


@app.command()
def bench(
    suite: str = typer.Option("refund", help="Suite name or YAML path"),
    variant: list[str] = typer.Option(None, help="Variants to run (default: all)"),
    model: str = typer.Option(None, envvar="MINDMESH_MODEL", help="Override model, e.g. ollama:qwen3:8b"),
    out: Path = typer.Option(Path("bench/results"), help="Where to write JSON/Markdown reports"),
    database_url: str = typer.Option(None, envvar="MINDMESH_DATABASE_URL", help="Store summaries in this DB"),
    project: str = typer.Option("default", envvar="MINDMESH_PROJECT"),
    store: bool = typer.Option(True, help="Store summaries in the project's eval history (Studio)"),
):
    """Run a reproducible benchmark suite and compare variants."""
    from .eval.report import to_markdown
    from .eval.runner import run_suite
    from .eval.suite import list_suites, load_suite

    async def go():
        s = load_suite(suite) if suite != "all" else None
        mm = await _mm(database_url, project).init() if store else None
        try:
            for one in ([s] if s else [load_suite(n) for n in list_suites()]):
                report = await run_suite(one, variants=variant or None, model=model, store=mm, results_dir=out)
                console.print(to_markdown(report))
                console.print(f"[dim]written: {report['files']}[/]")
        finally:
            if mm:
                await mm.close()

    aio.run(go())


@app.command("create-key")
def create_key(
    project: str = typer.Option("default", envvar="MINDMESH_PROJECT"),
    database_url: str = typer.Option(None, envvar="MINDMESH_DATABASE_URL"),
    name: str = typer.Option("cli"),
):
    """Create an API key for a project (creates the project if needed). The key is shown once."""

    async def go():
        mm = await _mm(database_url, project).init()
        try:
            key = await mm.db.create_api_key(mm.project_id, name)
            console.print(f"project [bold]{project}[/] ({mm.project_id})\nAPI key: [bold]{key}[/]")
        finally:
            await mm.close()

    aio.run(go())


@app.command("revoke-key")
def revoke_key(
    key: str = typer.Argument(..., help="The API key to revoke"),
    database_url: str = typer.Option(None, envvar="MINDMESH_DATABASE_URL"),
):
    """Revoke an API key. Servers stop accepting it within 30 seconds (auth cache TTL)."""

    async def go():
        db = _db(database_url)
        try:
            return await db.revoke_api_key(key)
        finally:
            await db.dispose()

    if not aio.run(go()):
        console.print("[yellow]no such key[/]")
        raise typer.Exit(1)
    console.print("[green]revoked.[/]")


def _db(database_url: str | None):
    from .storage.db import Database

    return Database(database_url or "sqlite:///mindmesh.db")


@db_app.command("upgrade")
def db_upgrade(
    revision: str = typer.Argument("head"),
    database_url: str = typer.Option(None, envvar="MINDMESH_DATABASE_URL"),
):
    """Apply migrations up to REVISION (default: head). Safe to run concurrently on PostgreSQL."""

    async def go():
        db = _db(database_url)
        try:
            await db.migrate(revision)
            return await db.current_revision()
        finally:
            await db.dispose()

    console.print(f"database at revision [bold]{aio.run(go())}[/]")


@db_app.command("current")
def db_current(database_url: str = typer.Option(None, envvar="MINDMESH_DATABASE_URL")):
    """Show the database's revision and the latest available one; exit 1 if behind."""
    from .storage.db import head_revision

    async def go():
        db = _db(database_url)
        try:
            return await db.current_revision()
        finally:
            await db.dispose()

    current, head = aio.run(go()), head_revision()
    console.print(f"current: [bold]{current}[/]  head: [bold]{head}[/]")
    if current != head:
        raise typer.Exit(1)


if __name__ == "__main__":  # pragma: no cover
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    app()
