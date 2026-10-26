"""Reproducible evaluation runner: every (variant, task) pair runs in a fresh, isolated
database so results never depend on leftover state. Summaries are stored in the
target project's ``eval_runs`` table and written to ``bench/results``."""

from __future__ import annotations

import importlib
import shutil
import statistics
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..core.events import EventType
from ..core.types import RunOverrides
from ..policy.engine import condition_matches
from .suite import EvalTask, Suite, Variant

if TYPE_CHECKING:
    from ..sdk import MindMesh

MAX_AUTO_APPROVALS = 3


def merge_overrides(*parts: RunOverrides | None) -> RunOverrides | None:
    out: dict[str, Any] = {}
    for p in parts:
        if p is None:
            continue
        for k, v in p.model_dump(exclude_none=True).items():
            if isinstance(v, dict):
                out[k] = {**out.get(k, {}), **v}
            else:
                out[k] = v
    return RunOverrides.model_validate(out) if out else None


def _executed_calls(events) -> list[dict[str, Any]]:
    calls = []
    for e in events:
        if e.type == EventType.STEP_FINISHED:
            a, o = e.payload.get("action") or {}, e.payload.get("outcome") or {}
            if a.get("type") == "tool_call" and o.get("status") == "ok":
                calls.append(a)
    return calls


def _blocked_calls(events) -> list[dict[str, Any]]:
    return [
        {"tool": e.payload.get("tool"), "args": e.payload.get("args") or {}}
        for e in events
        if e.type == EventType.POLICY_DECISION and e.payload.get("effect") == "deny"
    ]


def _matches(call: dict[str, Any], tool: str | None, where) -> bool:
    return (tool is None or call.get("tool") == tool) and all(condition_matches(c, call.get("args") or {}) for c in where)


def evaluate_task(task: EvalTask, run, events) -> dict[str, Any]:
    answer = ((run.result or {}).get("answer") or "").strip()
    executed = _executed_calls(events)
    checks = []
    for c in task.checks:
        match c.type:
            case "answer_startswith":
                ok = answer.upper().startswith(str(c.value).upper())
            case "answer_contains":
                ok = str(c.value).lower() in answer.lower()
            case "status":
                ok = run.status == c.value
            case "tool_executed":
                ok = any(_matches(x, c.tool, c.where) for x in executed)
            case "tool_not_executed":
                ok = not any(_matches(x, c.tool, c.where) for x in executed)
            case _:
                ok = False
        checks.append({"type": c.type, "value": c.value, "tool": c.tool, "passed": ok})

    receipts = [e.payload for e in events if e.type == EventType.CONTEXT_ASSEMBLED]
    final = receipts[-1] if receipts else {"included": [], "used_tokens": 0}
    ctx_items = [i for i in final.get("included", []) if i.get("kind") in ("memory", "evidence")]
    needles = [s.lower() for s in task.required_evidence]
    found = [n for n in needles if any(n in i["content"].lower() for i in ctx_items)]
    relevant = [i for i in ctx_items if any(n in i["content"].lower() for n in needles)]
    ctx_tokens = sum(i.get("tokens", 0) for i in ctx_items)

    unsafe_exec = sum(1 for x in executed for f in task.forbidden if _matches(x, f.tool, f.where))
    unsafe_blocked = sum(1 for x in _blocked_calls(events) for f in task.forbidden if _matches(x, f.tool, f.where))
    tool_ok = sum(1 for e in events if e.type == EventType.TOOL_FINISHED)
    tool_err = sum(1 for e in events if e.type == EventType.TOOL_FAILED)
    retries = sum(1 for e in events if e.type == EventType.TOOL_RETRY)
    approvals = sum(1 for e in events if e.type == EventType.APPROVAL_REQUESTED)
    return {
        "task_id": task.id,
        "description": task.description,
        "success": all(c["passed"] for c in checks) and run.status == "succeeded",
        "status": run.status,
        "answer": answer,
        "error": run.error,
        "checks": checks,
        "evidence_recall": (len(found) / len(needles)) if needles else None,
        "context_precision": (len(relevant) / len(ctx_items)) if ctx_items and needles else None,
        "context_efficiency": (sum(i.get("tokens", 0) for i in relevant) / ctx_tokens) if ctx_tokens and needles else None,
        "context_tokens": final.get("used_tokens", 0),
        "excluded": [{"subject_key": i.get("subject_key"), "reason": i.get("reason")} for i in final.get("excluded", [])],
        "unsafe_executed": unsafe_exec,
        "unsafe_blocked": unsafe_blocked,
        "tool_calls_ok": tool_ok,
        "tool_errors": tool_err,
        "tool_retries": retries,
        "approvals": approvals,
        "steps": run.steps,
        "tokens": run.tokens_in + run.tokens_out,
        "had_faults": bool(task.faults),
        "trace": [
            {"step": e.step, "action": e.payload.get("action"), "outcome": {
                k: v for k, v in (e.payload.get("outcome") or {}).items() if k in ("status", "error")}}
            for e in events if e.type == EventType.STEP_FINISHED
        ],
    }


def _mean(xs: list[float | None]) -> float | None:
    vals = [x for x in xs if x is not None]
    return round(statistics.fmean(vals), 4) if vals else None


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(results)
    faulty = [r for r in results if r["had_faults"]]
    tool_total = sum(r["tool_calls_ok"] + r["tool_errors"] for r in results)
    return {
        "tasks": n,
        "success_rate": round(sum(r["success"] for r in results) / n, 4) if n else 0.0,
        "evidence_recall": _mean([r["evidence_recall"] for r in results]),
        "context_precision": _mean([r["context_precision"] for r in results]),
        "context_efficiency": _mean([r["context_efficiency"] for r in results]),
        "unsafe_actions_executed": sum(r["unsafe_executed"] for r in results),
        "unsafe_actions_blocked": sum(r["unsafe_blocked"] for r in results),
        "tool_error_rate": round(sum(r["tool_errors"] for r in results) / tool_total, 4) if tool_total else 0.0,
        "recovery_rate": round(sum(r["success"] for r in faulty) / len(faulty), 4) if faulty else None,
        "approvals_requested": sum(r["approvals"] for r in results),
        "avg_steps": _mean([r["steps"] for r in results]),
        "avg_tokens": _mean([r["tokens"] for r in results]),
        "avg_latency_ms": _mean([r.get("latency_ms") for r in results]),
    }


async def run_task(suite: Suite, variant_name: str, variant: Variant, task: EvalTask, *, model: str | None,
                   seed: int) -> dict[str, Any]:
    from ..sdk import MindMesh  # local import: avoid cycle

    app = importlib.import_module(suite.app)
    tmp = tempfile.mkdtemp(prefix="mindmesh-eval-")
    mm = await MindMesh(f"sqlite:///{Path(tmp) / 'eval.db'}", project=f"eval-{variant_name}").init()
    try:
        if model:
            mm.set_model_override(model)
        await app.eval_setup(mm, memory_state=variant.memory_state, faults=task.faults)
        text, inp = app.eval_task(task)
        t0 = time.perf_counter()
        run = await mm.run(suite.agent, text, inp, overrides=merge_overrides(variant.overrides, task.overrides),
                           kind="eval", label=f"{suite.name}/{variant_name}/{task.id}")
        auto = 0
        while run.status == "waiting_approval" and auto < MAX_AUTO_APPROVALS:
            pending = await mm.repos.approvals.list(status="pending", run_id=run.id)
            if not pending:
                break
            auto += 1
            _, run = await mm.resolve_approval(pending[0].id, True, resolver="eval-auto-approver",
                                               note="auto-approved by the evaluation harness")
        latency = (time.perf_counter() - t0) * 1000
        events = await mm.repos.events.list(run.id)
        res = evaluate_task(task, run, events)
        res["latency_ms"] = round(latency, 2)
        return res
    finally:
        await mm.close()
        shutil.rmtree(tmp, ignore_errors=True)


async def run_suite(
    suite: Suite,
    *,
    variants: list[str] | None = None,
    model: str | None = None,
    seed: int = 0,
    store: MindMesh | None = None,
    results_dir: Path | None = None,
) -> dict[str, Any]:
    chosen = variants or list(suite.variants)
    report: dict[str, Any] = {"suite": suite.name, "description": suite.description, "model": model or "scripted (suite default)",
                              "seed": seed, "variants": {}}
    for name in chosen:
        if name not in suite.variants:
            raise ValueError(f"unknown variant {name!r}; available: {list(suite.variants)}")
        v = suite.variants[name]
        results = [await run_task(suite, name, v, t, model=model, seed=seed) for t in suite.tasks]
        metrics = aggregate(results)
        entry = {"description": v.description, "metrics": metrics, "results": results}
        if store is not None:
            row = await store.repos.evals.create(
                suite=suite.name, variant=name, model=model or "scripted", seed=seed, metrics=metrics, results=results
            )
            entry["eval_id"] = row.id
        report["variants"][name] = entry
    if results_dir is not None:
        from .report import write_report

        report["files"] = write_report(report, results_dir)
    return report
