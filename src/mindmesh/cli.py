"""``mindmesh`` command line: serve the API, run the signature demo, seed data, run benchmarks."""

from __future__ import annotations

import os
from pathlib import Path

import typer
from rich import box
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
    settings = Settings.from_env()
    if not settings.is_production:
        console.print(f"Studio: [bold]http://{host}:{port}[/]  (API key: {settings.resolved_api_key()})")
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
    from .demo.showcase import reset_project

    await reset_project(mm)


@demo_app.command("seed")
def demo_seed(
    database_url: str = typer.Option(None, envvar="MINDMESH_DATABASE_URL"),
    project: str = typer.Option("default", envvar="MINDMESH_PROJECT"),
    model: str = typer.Option(None, envvar="MINDMESH_MODEL"),
):
    """Seed the broken refund scenario + a few runs and a workflow so Studio has data to explore."""
    aio.run(_seed(database_url, project, model))


async def _seed(database_url, project, model):
    from .demo import refund, research, showcase

    mm = await _mm(database_url, project).init()
    try:
        if model:
            mm.set_model_override(model)
        refund.install(mm)
        research.install(mm)
        await showcase.seed(mm, echo=console.print)
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


@app.command("create-key", hidden=True)
def create_key(
    project: str = typer.Option("default", envvar="MINDMESH_PROJECT"),
    database_url: str = typer.Option(None, envvar="MINDMESH_DATABASE_URL"),
    name: str = typer.Option("cli"),
    role: str = typer.Option("admin", help="admin (full access) or read (read-only, e.g. a public demo)"),
):
    """Create an API key for a project (creates the project if needed). The key is shown once."""

    async def go():
        mm = await _mm(database_url, project).init()
        try:
            key = await mm.db.create_api_key(mm.project_id, name, role=role)
            console.print(f"project [bold]{project}[/] ({mm.project_id}) role [bold]{role}[/]\nAPI key: [bold]{key}[/]")
        finally:
            await mm.close()

    aio.run(go())


@app.command("revoke-key", hidden=True)
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


# ---------------------------------------------------------------------------------------- projects & keys

projects_app = typer.Typer(help="Projects: isolated tenants with their own runs, memory, policies and keys.",
                           no_args_is_help=True)
app.add_typer(projects_app, name="projects")
keys_app = typer.Typer(help="API keys (admin: full access, read: read-only).", no_args_is_help=True)
app.add_typer(keys_app, name="keys")
runs_app = typer.Typer(help="Inspect, replay, rerun, export and import runs.", no_args_is_help=True)
app.add_typer(runs_app, name="runs")
evals_app = typer.Typer(help="Benchmark results.", no_args_is_help=True)
app.add_typer(evals_app, name="evals")

DB_OPT = typer.Option(None, "--database-url", envvar="MINDMESH_DATABASE_URL", help="Default: sqlite:///mindmesh.db")
PROJECT_OPT = typer.Option("default", "--project", "-p", envvar="MINDMESH_PROJECT")
APP_OPT = typer.Option(None, "--app", help="Module(s) whose install(mm) registers your tools and agents "
                                           "(comma-separated), e.g. my_agent")


FREE_TEXT = {"result", "task", "args", "outcome"}
MIN_WIDTH = {"id": 26, "created": 11, "last used": 11, "status": 16, "prefix": 11}


def _table(*columns: str) -> Table:
    """Ids and timestamps are shown in full (they are meant to be copied); free text wraps in the remaining
    width."""
    t = Table(box=box.SIMPLE_HEAD)
    for c in columns:
        if c in FREE_TEXT:
            t.add_column(c, overflow="fold")
        else:
            t.add_column(c, no_wrap=True, min_width=max(len(c), MIN_WIDTH.get(c, 0)))
    return t


def _run(coro):
    """``aio.run`` for CLI commands: unknown ids and invalid input end with a message, not a traceback."""
    from .core.errors import NotFound

    try:
        return aio.run(coro)
    except (NotFound, ValueError) as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(1) from None


def _fmt_ts(ts) -> str:
    return ts.strftime("%m-%d %H:%M") if ts else "never"


def _write_json(doc: dict, out: Path | None) -> None:
    import json

    text = json.dumps(doc, indent=2, default=str)
    if out is None:
        typer.echo(text)
    else:
        out.write_text(text, encoding="utf-8")
        console.print(f"[green]wrote[/] {out} ({len(text) // 1024 + 1} KiB)")


async def _open(database_url: str | None, project: str, apps: str | None = None):
    mm = await _mm(database_url, project).init()
    if apps:
        from .server.app import install_apps

        install_apps(mm, apps)
    return mm


@projects_app.command("list")
def projects_list(database_url: str = DB_OPT):
    """Projects with their key and run counts."""
    from sqlalchemy import func, select

    from .storage.orm import ApiKeyRow, RunRow

    async def go():
        db = _db(database_url)
        try:
            await db.migrate()
            async with db.session() as s:
                keys = dict((await s.execute(select(ApiKeyRow.project_id, func.count()).group_by(ApiKeyRow.project_id))).all())
                runs = dict((await s.execute(select(RunRow.project_id, func.count()).group_by(RunRow.project_id))).all())
            return [(p, keys.get(p.id, 0), runs.get(p.id, 0)) for p in await db.list_projects()]
        finally:
            await db.dispose()

    t = _table("project", "id", "keys", "runs", "created")
    for p, k, r in _run(go()):
        t.add_row(p.name, p.id, str(k), str(r), _fmt_ts(p.created_at))
    console.print(t)


@projects_app.command("create")
def projects_create(
    name: str = typer.Argument(..., help="Project name"),
    database_url: str = DB_OPT,
    key: bool = typer.Option(True, help="Also create an admin key for it"),
):
    """Create a project (idempotent) and, by default, its first admin key."""

    async def go():
        mm = await _mm(database_url, name).init()
        try:
            return mm.project_id, (await mm.db.create_api_key(mm.project_id, "admin") if key else None)
        finally:
            await mm.close()

    pid, k = _run(go())
    console.print(f"project [bold]{name}[/] ({pid})")
    if k:
        console.print(f"admin key (shown once): [bold]{k}[/]")


@keys_app.command("list")
def keys_list(project: str = typer.Option(None, "--project", "-p", help="Only this project"), database_url: str = DB_OPT):
    """Key metadata: id, project, name, role, prefix, created, last used. Secrets are never shown."""

    async def go():
        db = _db(database_url)
        try:
            await db.migrate()
            names = {p.id: p.name for p in await db.list_projects()}
            pid = next((i for i, n in names.items() if n == project), "-") if project else None
            return names, await db.list_api_keys(pid)
        finally:
            await db.dispose()

    names, rows = _run(go())
    if not rows:
        console.print("[dim]no keys[/]")
    for r in rows:
        console.print(f"[bold]{r.id}[/]  {names.get(r.project_id, r.project_id)}  {r.name}  "
                      f"[{'cyan' if r.role == 'read' else 'magenta'}]{r.role}[/]  {r.prefix or '?'}…  "
                      f"[dim]last used {_fmt_ts(r.last_used_at)}[/]")


@keys_app.command("create")
def keys_create(
    project: str = PROJECT_OPT,
    database_url: str = DB_OPT,
    name: str = typer.Option("cli", help="A label, e.g. ci or alice-laptop"),
    role: str = typer.Option("admin", help="admin (full access) or read (read-only)"),
):
    """Create an API key (creates the project if needed). The key is shown once."""
    create_key(project=project, database_url=database_url, name=name, role=role)


@keys_app.command("revoke")
def keys_revoke(
    key_or_id: str = typer.Argument(..., help="The key itself, or its id from `mindmesh keys list`"),
    database_url: str = DB_OPT,
):
    """Revoke a key. Running servers stop accepting it within 30 seconds (auth cache TTL)."""

    async def go():
        db = _db(database_url)
        try:
            if key_or_id.startswith("key_"):
                return await db.revoke_api_key_id(key_or_id)
            return await db.revoke_api_key(key_or_id)
        finally:
            await db.dispose()

    if not _run(go()):
        console.print("[yellow]no such key[/]")
        raise typer.Exit(1)
    console.print("[green]revoked.[/]")


# ------------------------------------------------------------------------------------------------- runs


@runs_app.command("list")
def runs_list(
    project: str = PROJECT_OPT,
    database_url: str = DB_OPT,
    status: str = typer.Option(None, help="e.g. failed, succeeded, waiting_approval"),
    agent: str = typer.Option(None),
    limit: int = typer.Option(20),
):
    """The newest runs of a project."""

    async def go():
        mm = await _open(database_url, project)
        try:
            return await mm.repos.runs.list(status=status, agent=agent, limit=limit)
        finally:
            await mm.close()

    rows = _run(go())
    if not rows:
        console.print("[dim]no runs[/]")
    color = {"succeeded": "green", "failed": "red", "cancelled": "red"}
    for r in rows:
        status = r.status if r.kind == "live" else f"{r.status} ({r.kind})"
        console.print(f"[bold]{r.id}[/]  [{color.get(r.status, 'yellow')}]{status}[/]  {r.agent_name}  "
                      f"[dim]{_fmt_ts(r.created_at)}, {r.steps} steps[/]")
        outcome = (r.result or {}).get("answer") or r.error
        if outcome:
            console.print(f"    {outcome}", overflow="ellipsis", no_wrap=True)


@runs_app.command("show")
def runs_show(run_id: str, project: str = PROJECT_OPT, database_url: str = DB_OPT):
    """What happened in a run: outcome, cost, each step with its policy decision, and the context it used."""
    from .core.events import EventType
    from .export import summarize

    async def go():
        mm = await _open(database_url, project)
        try:
            run = await mm.repos.runs.get(run_id)
            events = await mm.repos.events.list(run_id)
            return run, events, summarize(run, events)
        finally:
            await mm.close()

    run, events, s = _run(go())
    color = {"succeeded": "green", "failed": "red"}.get(s["status"], "yellow")
    console.print(Panel.fit(
        f"[bold]{run.id}[/]  agent [bold]{s['agent']}[/]  model {s['model']}  [{color}]{s['status']}[/]\n"
        f"task: {run.task}\n"
        f"result: {s['answer'] or s['error'] or '-'}\n"
        f"{s['steps']} steps, {s['tool_calls']} tool calls, {s['tokens_in']}+{s['tokens_out']} tokens"
        + (f", {s['duration_ms']:.0f} ms" if s["duration_ms"] is not None else "")
        + (f"\nfeedback: {s['feedback']}" if s["feedback"] else "")))
    t = _table("step", "action", "args", "outcome")
    policy = {(e.step, e.payload.get("tool")): e.payload for e in events if e.type == EventType.POLICY_DECISION}
    for st in s["timeline"]:
        p = policy.get((st["step"], st["tool"]))
        outcome = st["status"] or ""
        if p and p.get("effect") != "allow":
            outcome += f" (policy {p.get('effect')}: {p.get('rule_name') or p.get('reason')})"
        if st["error"]:
            outcome += f" - {st['error']}"
        t.add_row(str(st["step"]), st["tool"] or "final_answer", str(st["args"] or "")[:60], outcome[:90])
    console.print(t)
    receipts = [e for e in events if e.type == EventType.CONTEXT_ASSEMBLED]
    if receipts and (receipts[-1].payload["excluded"]
                     or any(i["kind"] != "task" for i in receipts[-1].payload["included"])):
        _print_receipt(receipts[-1].payload)


@runs_app.command("replay")
def runs_replay(run_id: str, project: str = PROJECT_OPT, database_url: str = DB_OPT):
    """Safe replay: re-run the decisions from recorded model outputs and tool results. Nothing is executed,
    so it works without the agent's code and is safe for side-effecting tools."""

    async def go():
        mm = await _open(database_url, project)
        try:
            original = await mm.repos.runs.get(run_id)
            r = await mm.replay(run_id)
            return original, r, await mm.compare(run_id, r.id)
        finally:
            await mm.close()

    original, r, cmp = _run(go())
    console.print(f"replay {r.id}: [bold]{r.status}[/] -> {(r.result or {}).get('answer') or r.error}")
    differences = []
    if r.status != original.status or (r.result or {}).get("answer") != (original.result or {}).get("answer"):
        differences.append("outcome differs from the original")
    steps = cmp.get("steps", [])
    first = next((st["step"] for st in steps if not st.get("same_action")), None)
    if first is not None:
        differences.append(f"actions diverge at step {first}")
    for st in steps:
        a, b = st.get("a") or {}, st.get("b") or {}
        if (a.get("outcome") or {}).get("status") != (b.get("outcome") or {}).get("status"):
            differences.append(f"step {st['step']} outcome differs")
            break
    if differences:
        console.print(f"[yellow]did not reproduce the original: {'; '.join(differences)}[/]")
        raise typer.Exit(1)
    console.print("[green]reproduced the original run: same actions, outcomes and answer[/]")
    if cmp.get("divergence_step") is not None:
        console.print(f"[dim]context differs from step {cmp['divergence_step']}: replay assembles context from this "
                      "database's current memories and policies[/]")


@runs_app.command("rerun")
def runs_rerun(
    run_id: str,
    project: str = PROJECT_OPT,
    database_url: str = DB_OPT,
    apps: str = APP_OPT,
    model: str = typer.Option(None, help="Override the model, e.g. ollama:qwen3:4b"),
):
    """Execute the run's task again, live, with the current memory, policies and agent code; then compare."""
    from .core.types import RunOverrides

    async def go():
        mm = await _open(database_url, project, apps)
        try:
            r = await mm.rerun(run_id, RunOverrides(model=model) if model else None)
            return r, await mm.compare(run_id, r.id)
        finally:
            await mm.close()

    r, cmp = _run(go())
    console.print(f"rerun {r.id}: [bold]{r.status}[/] -> {(r.result or {}).get('answer') or r.error}")
    step = cmp.get("divergence_step")
    console.print(f"first divergence at step {step}" if step is not None else "same decisions as the original")


@runs_app.command("export")
def runs_export(
    run_ids: list[str] = typer.Argument(None, help="Run ids (default: the newest runs matching the filters)"),
    project: str = PROJECT_OPT,
    database_url: str = DB_OPT,
    status: str = typer.Option(None),
    limit: int = typer.Option(20),
    out: Path = typer.Option(None, "--out", "-o", help="Write to this file (default: stdout)"),
):
    """Export runs as JSON: one id gives a mindmesh.run/v1 document, otherwise mindmesh.runs/v1."""
    from .export import export_run, export_runs

    async def go():
        mm = await _open(database_url, project)
        try:
            if run_ids and len(run_ids) == 1:
                return await export_run(mm, run_ids[0])
            return await export_runs(mm, run_ids or None, **({} if run_ids else {"status": status, "limit": limit}))
        finally:
            await mm.close()

    _write_json(_run(go()), out)


@runs_app.command("import")
def runs_import(
    file: Path = typer.Argument(..., exists=True, help="A mindmesh.run/v1 or mindmesh.runs/v1 file"),
    project: str = PROJECT_OPT,
    database_url: str = DB_OPT,
):
    """Import exported runs under new ids (e.g. a failure a teammate shared), ready to inspect and replay."""
    import json

    from .export import RUNS_FORMAT, import_run

    doc = json.loads(file.read_text(encoding="utf-8"))
    docs = doc["runs"] if doc.get("format") == RUNS_FORMAT else [doc]

    async def go():
        mm = await _open(database_url, project)
        try:
            return [await import_run(mm, d) for d in docs]
        finally:
            await mm.close()

    for r in _run(go()):
        console.print(f"imported [bold]{r.id}[/] ({r.label}): {r.status}. "
                      f"Inspect: mindmesh runs show {r.id} -p {project}   Replay: mindmesh runs replay {r.id} -p {project}")


@evals_app.command("list")
def evals_list(project: str = PROJECT_OPT, database_url: str = DB_OPT, suite: str = typer.Option(None)):
    """Stored benchmark results (see `mindmesh bench`)."""

    async def go():
        mm = await _open(database_url, project)
        try:
            return await mm.repos.evals.list(suite=suite)
        finally:
            await mm.close()

    t = _table("id", "suite", "variant", "model", "success", "created")
    for r in _run(go()):
        rate = r.metrics.get("success_rate")
        t.add_row(r.id, r.suite, r.variant, r.model, f"{rate:.0%}" if isinstance(rate, int | float) else "-",
                  _fmt_ts(r.created_at))
    console.print(t)


@evals_app.command("export")
def evals_export(
    eval_ids: list[str] = typer.Argument(None, help="Eval ids (default: all, newest first)"),
    project: str = PROJECT_OPT,
    database_url: str = DB_OPT,
    suite: str = typer.Option(None),
    out: Path = typer.Option(None, "--out", "-o", help="Write to this file (default: stdout)"),
):
    """Export benchmark results (metrics per variant and per-task results) as mindmesh.eval/v1 JSON."""
    from .export import export_evals

    async def go():
        mm = await _open(database_url, project)
        try:
            return await export_evals(mm, eval_ids or None, suite=suite)
        finally:
            await mm.close()

    _write_json(_run(go()), out)


if __name__ == "__main__":  # pragma: no cover
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    app()
