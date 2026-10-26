"""Step-aligned comparison of two runs (original vs. replay/rerun)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from ..core import clock
from ..core.events import EventType
from ..core.types import Run

if TYPE_CHECKING:
    from ..sdk import MindMesh


def _action_key(action: dict[str, Any] | None) -> str:
    if not action:
        return "-"
    if action.get("type") == "final_answer":
        return f"final:{action.get('answer', '')}"
    return f"tool:{action.get('tool')}:{json.dumps(action.get('args', {}), sort_keys=True)}"


def _summary(run: Run) -> dict[str, Any]:
    dur = None
    if run.started_at and run.ended_at:
        dur = (clock.ensure_aware(run.ended_at) - clock.ensure_aware(run.started_at)).total_seconds() * 1000
    return {
        "id": run.id,
        "status": run.status,
        "kind": run.kind,
        "label": run.label,
        "steps": run.steps,
        "tool_calls": run.tool_calls,
        "tokens": run.tokens_in + run.tokens_out,
        "duration_ms": dur,
        "answer": (run.result or {}).get("answer"),
        "error": run.error,
        "model": (run.config.get("agent_spec") or {}).get("model"),
    }


async def _steps(mm: MindMesh, run_id: str) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    events = await mm.repos.events.list(
        run_id, types=[EventType.STEP_FINISHED, EventType.CONTEXT_ASSEMBLED, EventType.POLICY_DECISION]
    )
    for e in events:
        if e.step is None:
            continue
        s = out.setdefault(e.step, {"step": e.step, "policy": []})
        if e.type == EventType.STEP_FINISHED:
            s["action"] = e.payload.get("action")
            s["outcome"] = e.payload.get("outcome")
        elif e.type == EventType.CONTEXT_ASSEMBLED:
            s["context_ids"] = [i["item_id"] for i in e.payload.get("included", []) if i.get("kind") == "memory"]
            s["context_tokens"] = e.payload.get("used_tokens")
            s["excluded"] = {i["item_id"]: i.get("reason") for i in e.payload.get("excluded", [])}
        elif e.type == EventType.POLICY_DECISION:
            s["policy"].append({"tool": e.payload.get("tool"), "effect": e.payload.get("effect")})
    return out


async def compare_runs(mm: MindMesh, run_a: str, run_b: str) -> dict[str, Any]:
    a, b = await mm.repos.runs.get(run_a), await mm.repos.runs.get(run_b)
    sa, sb = await _steps(mm, run_a), await _steps(mm, run_b)
    rows = []
    divergence: int | None = None
    for i in range(1, max([0, *sa.keys(), *sb.keys()]) + 1):
        x, y = sa.get(i, {}), sb.get(i, {})
        same_action = _action_key(x.get("action")) == _action_key(y.get("action"))
        ctx_a, ctx_b = set(x.get("context_ids", [])), set(y.get("context_ids", []))
        if divergence is None and (not same_action or ctx_a != ctx_b):
            divergence = i
        rows.append(
            {
                "step": i,
                "a": {k: x.get(k) for k in ("action", "outcome", "policy", "context_tokens")},
                "b": {k: y.get(k) for k in ("action", "outcome", "policy", "context_tokens")},
                "same_action": same_action,
                "context_added": sorted(ctx_b - ctx_a),
                "context_removed": sorted(ctx_a - ctx_b),
            }
        )
    # Explain context deltas with the memory content (Replay Lab shows these).
    ids = {m for r in rows for m in r["context_added"] + r["context_removed"]}
    memories = {}
    for mid in ids:
        try:
            m = await mm.memory.get(mid)
            memories[mid] = {"content": m.content, "scope": m.scope, "status": m.status, "subject_key": m.subject_key}
        except Exception:  # noqa: BLE001 - memory may belong to evidence, not the store
            continue
    sum_a, sum_b = _summary(a), _summary(b)
    return {
        "a": sum_a,
        "b": sum_b,
        "steps": rows,
        "divergence_step": divergence,
        "identical": divergence is None and sum_a["answer"] == sum_b["answer"] and sum_a["status"] == sum_b["status"],
        "memories": memories,
        "delta": {
            "status_changed": sum_a["status"] != sum_b["status"],
            "steps": (sum_b["steps"] or 0) - (sum_a["steps"] or 0),
            "tool_calls": (sum_b["tool_calls"] or 0) - (sum_a["tool_calls"] or 0),
            "tokens": (sum_b["tokens"] or 0) - (sum_a["tokens"] or 0),
        },
    }
