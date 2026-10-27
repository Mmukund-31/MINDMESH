"""Fixtures for the live suite: the refund scenario driven by a genuine model.

    ollama pull qwen3:4b
    pytest -m ollama tests/live                      # SQLite
    MINDMESH_TEST_DATABASE_URL=postgresql://... pytest -m ollama tests/live

``MINDMESH_LIVE_MODEL`` picks the model (default ``ollama:qwen3:4b``). Every test records a
trace summary of its runs; the session writes them to ``bench/results/live/`` as the proof report.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from mindmesh import MindMesh
from mindmesh.demo import refund
from mindmesh.models.ollama import OllamaProvider

LIVE_MODEL = os.environ.get("MINDMESH_LIVE_MODEL", "ollama:qwen3:4b")
REPORT: dict[str, Any] = {"model": LIVE_MODEL, "tests": {}}


@pytest.fixture(scope="session")
def live_model() -> str:
    prefix, _, name = LIVE_MODEL.partition(":")
    if prefix != "ollama":
        pytest.skip(f"live suite supports ollama models, not {LIVE_MODEL!r}")
    base = OllamaProvider(name).base_url
    try:
        tags = httpx.get(f"{base}/api/tags", timeout=5).json()
    except httpx.HTTPError:
        pytest.skip(f"Ollama is not reachable at {base}")
    if not any(name in (m.get("name"), m.get("model")) for m in tags.get("models", [])):
        pytest.skip(f"model {name!r} is not pulled (ollama pull {name})")
    return LIVE_MODEL


@pytest.fixture(scope="session", autouse=True)
def _write_report():
    started = time.time()
    yield
    if not REPORT["tests"]:
        return
    out = Path("bench/results/live")
    out.mkdir(parents=True, exist_ok=True)
    REPORT["database"] = "postgresql" if os.environ.get("MINDMESH_TEST_DATABASE_URL", "").startswith(
        "postgres") else "sqlite"
    REPORT["wall_s"] = round(time.time() - started, 1)
    name = f"live-proof-{LIVE_MODEL.replace(':', '_')}-{time.strftime('%Y%m%d-%H%M%S')}.json"
    (out / name).write_text(json.dumps(REPORT, indent=2, default=str), encoding="utf-8")


@pytest.fixture
async def live(mm, live_model):
    """The refund scenario with correct memory, every agent forced onto the live model."""
    world = refund.install(mm)
    await refund.seed(mm, memory_state="fixed")
    mm.set_model_override(live_model)
    mm.world = world  # type: ignore[attr-defined]
    return mm


@pytest.fixture
def record(request):
    """``await record(mm, run_id, **extra)`` adds a run's trace summary to the proof report."""

    async def _record(mm: MindMesh, run_id: str, **extra: Any) -> dict[str, Any]:
        summary = await trace_summary(mm, run_id)
        summary.update(extra)
        REPORT["tests"].setdefault(request.node.name, []).append(summary)
        return summary

    return _record


async def trace_summary(mm: MindMesh, run_id: str) -> dict[str, Any]:
    run = await mm.repos.runs.get(run_id)
    events = await mm.repos.events.list(run_id)
    calls, failures, policy, tools, other = [], [], [], [], []
    for e in events:
        p = e.payload
        if e.type == "model.called":
            calls.append({k: p.get(k) for k in (
                "model", "model_reported", "model_digest", "stop_reason", "attempt", "tokens_in", "tokens_out",
                "usage_reported", "latency_ms", "wall_ms", "provider_timing_ms")} | {"step": e.step,
                                                                                     "response": p.get("response")})
        elif e.type == "model.failed":
            failures.append({"step": e.step, **p})
        elif e.type == "policy.decision":
            policy.append({"step": e.step, "tool": p.get("tool"), "args": p.get("args"), "effect": p.get("effect"),
                           "rule": p.get("rule_name"), "reason": p.get("reason")})
        elif e.type in ("tool.finished", "tool.failed") and "kind" not in p:
            tools.append({"step": e.step, "tool": p.get("tool"), "ok": e.type == "tool.finished",
                          "result": p.get("result"), "error": p.get("error"), "replayed": p.get("replayed", False),
                          "duration_ms": e.duration_ms})
        elif e.type in ("run.resumed", "guard.triggered", "replay.diverged", "approval.requested",
                        "approval.resolved", "budget.exceeded"):
            other.append({"type": e.type, "step": e.step, **p})
    return {
        "run_id": run.id, "kind": run.kind, "status": str(run.status),
        "answer": (run.result or {}).get("answer"), "error": run.error, "steps": run.steps,
        "tool_calls": run.tool_calls, "tokens_in": run.tokens_in, "tokens_out": run.tokens_out,
        "duration_s": round((run.ended_at - run.started_at).total_seconds(), 2)
        if run.started_at and run.ended_at else None,
        "model_calls": calls, "model_failures": failures, "policy_decisions": policy, "tools": tools,
        "events": other, "event_count": len(events),
    }
