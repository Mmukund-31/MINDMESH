"""Turn a run's flat event log into a step tree for Execution Studio."""

from __future__ import annotations

from typing import Any

from ..core.events import EventType
from ..core.types import Event


def build_trace(events: list[Event]) -> dict[str, Any]:
    steps: dict[int, dict[str, Any]] = {}
    run_events: list[dict[str, Any]] = []
    tools: dict[str, dict[str, Any]] = {}
    for e in events:
        ev = e.model_dump(mode="json")
        if e.step is None or e.type in (EventType.RUN_STATE, EventType.RUN_CREATED, EventType.RUN_RESUMED):
            run_events.append(ev)
            continue
        s = steps.setdefault(
            e.step,
            {"step": e.step, "span_id": None, "status": "running", "started_at": None, "ended_at": None,
             "action": None, "outcome": None, "nodes": []},
        )
        match e.type:
            case EventType.STEP_STARTED:
                s["span_id"], s["started_at"] = e.span_id, ev["ts"]
            case EventType.STEP_FINISHED:
                s["ended_at"] = ev["ts"]
                s["action"] = e.payload.get("action")
                s["outcome"] = e.payload.get("outcome")
                s["status"] = (s["outcome"] or {}).get("status", "done")
            case EventType.CHECKPOINT_SAVED:
                s["checkpointed"] = True
            case EventType.TOOL_STARTED:
                node = {"kind": "tool", "span_id": e.span_id, "tool": e.payload.get("tool"), "args": e.payload.get("args"),
                        "started_at": ev["ts"], "status": "running", "events": [ev], "seq": e.seq}
                tools[e.span_id] = node
                s["nodes"].append(node)
            case EventType.TOOL_FINISHED | EventType.TOOL_FAILED if e.span_id in tools:
                node = tools[e.span_id]
                node["status"] = "ok" if e.type == EventType.TOOL_FINISHED else "error"
                node["result"] = e.payload.get("result")
                node["error"] = e.payload.get("error")
                node["duration_ms"] = e.duration_ms
                node["events"].append(ev)
            case EventType.TOOL_RETRY if e.parent_span_id in tools:
                tools[e.parent_span_id].setdefault("retries", []).append(e.payload)
                tools[e.parent_span_id]["events"].append(ev)
            case _:
                kind = {
                    EventType.CONTEXT_ASSEMBLED: "context",
                    EventType.MODEL_CALLED: "model",
                    EventType.MODEL_FAILED: "model_error",
                    EventType.POLICY_DECISION: "policy",
                    EventType.APPROVAL_REQUESTED: "approval",
                    EventType.APPROVAL_RESOLVED: "approval_resolved",
                    EventType.TOOL_FAILED: "tool",
                    EventType.GUARD_TRIGGERED: "guard",
                    EventType.BUDGET_EXCEEDED: "budget",
                    EventType.REPLAY_DIVERGED: "divergence",
                }.get(e.type, "event")
                s["nodes"].append({"kind": kind, "type": e.type, "span_id": e.span_id, "seq": e.seq, "event": ev})
    return {"steps": [steps[k] for k in sorted(steps)], "run_events": run_events}
