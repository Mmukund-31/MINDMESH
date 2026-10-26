from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import timedelta

from fastapi import APIRouter, Depends

from ...core import clock
from ...core.events import EventType
from ...sdk import MindMesh
from ..deps import project_mm

router = APIRouter(tags=["overview"])


def _pct(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))], 1)


@router.get("/me")
async def me(mm: MindMesh = Depends(project_mm)):
    projects = {p.id: p.name for p in await mm.db.list_projects()}
    return {"project_id": mm.project_id, "project_name": projects.get(mm.project_id)}


@router.get("/stats/overview")
async def overview(days: int = 14, mm: MindMesh = Depends(project_mm)):
    now = clock.now()
    since = now - timedelta(days=days)
    runs = [r for r in await mm.repos.runs.all_rows(since=since)]
    status = Counter(r.status for r in runs)
    terminal = [r for r in runs if r.status in ("succeeded", "failed", "cancelled")]
    durations = [
        (clock.ensure_aware(r.ended_at) - clock.ensure_aware(r.started_at)).total_seconds() * 1000
        for r in terminal if r.started_at and r.ended_at
    ]
    by_day: dict[str, Counter] = defaultdict(Counter)
    for r in runs:
        by_day[clock.ensure_aware(r.created_at).date().isoformat()][r.status] += 1
    series = []
    for i in range(days - 1, -1, -1):
        d = (now - timedelta(days=i)).date().isoformat()
        c = by_day.get(d, Counter())
        series.append({"date": d, "succeeded": c["succeeded"], "failed": c["failed"] + c["cancelled"],
                       "other": sum(c.values()) - c["succeeded"] - c["failed"] - c["cancelled"]})

    tool_events = await mm.repos.events.by_type([EventType.TOOL_FINISHED, EventType.TOOL_FAILED], limit=5000)
    tools: dict[str, Counter] = defaultdict(Counter)
    for e in tool_events:
        tools[e.payload.get("tool", "?")]["ok" if e.type == EventType.TOOL_FINISHED else "error"] += 1
    decisions = await mm.repos.events.by_type([EventType.POLICY_DECISION], limit=5000)
    effects = Counter(e.payload.get("effect") for e in decisions)
    failures = sorted(
        [r for r in runs if r.status in ("failed", "cancelled")
         or ((r.result or {}).get("answer", "").startswith("ESCALATED"))
         or (r.feedback or {}).get("verdict") == "incorrect"],
        key=lambda r: r.created_at, reverse=True,
    )[:10]
    mem_status = await mm.repos.memories.count_by_status()
    evals = await mm.repos.evals.list(limit=30)
    latest: dict[str, dict] = {}
    for ev in evals:
        latest.setdefault(f"{ev.suite}/{ev.variant}", {"suite": ev.suite, "variant": ev.variant, "id": ev.id,
                                                       "created_at": ev.created_at, "metrics": ev.metrics})
    return {
        "window_days": days,
        "runs": {
            "total": len(runs),
            "by_status": dict(status),
            "success_rate": round(status["succeeded"] / len(terminal), 4) if terminal else None,
            "avg_steps": round(statistics.fmean([r.steps for r in terminal]), 2) if terminal else None,
            "tokens": sum(r.tokens_in + r.tokens_out for r in runs),
            "tool_calls": sum(r.tool_calls for r in runs),
            "latency_p50_ms": _pct(durations, 0.5),
            "latency_p95_ms": _pct(durations, 0.95),
        },
        "series": series,
        "tools": [{"tool": k, "ok": v["ok"], "error": v["error"]} for k, v in sorted(tools.items())],
        "policy": {"decisions": dict(effects),
                   "pending_approvals": len(await mm.repos.approvals.list(status="pending"))},
        "recent_failures": [
            {"id": r.id, "agent": r.agent_name, "status": r.status, "task": r.task[:160], "error": r.error,
             "answer": (r.result or {}).get("answer"), "feedback": r.feedback, "kind": r.kind,
             "created_at": r.created_at}
            for r in failures
        ],
        "memory": mem_status,
        "evals": list(latest.values()),
    }
