"""Safe replay and rerun of recorded runs.

* **Safe replay** re-executes a run with the *recorded* model outputs and tool
  results. No model is called and no tool is executed, so it is safe for runs with
  side effects; it verifies the runtime reproduces the same decisions (determinism)
  and re-evaluates *current* policies and context against the recorded behaviour.
* **Rerun** executes the same task again, live, with optional config overrides
  (model, memory scopes, context budget, limits). After fixing memory or policies,
  a rerun shows whether the fix works; :mod:`mindmesh.replay.diff` compares the two.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..core.events import EventType
from ..core.state import TERMINAL_RUN, RunStatus
from ..core.types import AgentSpec, ModelResponse, Run, RunOverrides
from ..models.scripted import RecordedProvider

if TYPE_CHECKING:
    from ..sdk import MindMesh


async def load_recording(
    mm: MindMesh, run_id: str
) -> tuple[dict[int, list[ModelResponse]], dict[int, dict[str, Any]]]:
    """Recorded model responses and tool outcomes, keyed by step.

    If a step was executed more than once (it was interrupted and redone during crash recovery),
    only the final attempt sequence counts: a new sequence starts at every ``attempt == 1``.
    Each outcome carries the recorded action under ``recorded_action`` so replay can detect divergence.
    """
    events = await mm.repos.events.list(run_id, types=[EventType.MODEL_CALLED, EventType.STEP_FINISHED])
    responses: dict[int, list[ModelResponse]] = {}
    outcomes: dict[int, dict[str, Any]] = {}
    for e in events:
        if e.type == EventType.MODEL_CALLED and e.step is not None:
            p = e.payload
            if p.get("attempt", 1) == 1:
                responses[e.step] = []
            responses.setdefault(e.step, []).append(
                ModelResponse(
                    text=p.get("response", ""),
                    model=f"replay:{p.get('model', '?')}",
                    tokens_in=p.get("tokens_in", 0),
                    tokens_out=p.get("tokens_out", 0),
                    latency_ms=0.0,
                    model_reported=p.get("model_reported"),
                    model_digest=p.get("model_digest"),
                )
            )
        elif e.type == EventType.STEP_FINISHED and e.step is not None:
            outcomes[e.step] = {**e.payload.get("outcome", {}), "recorded_action": e.payload.get("action")}
    return responses, outcomes


async def safe_replay(mm: MindMesh, run_id: str, *, wait: bool = True) -> Run:
    original = await mm.repos.runs.get(run_id)
    if RunStatus(original.status) not in TERMINAL_RUN:
        raise ValueError("only finished runs can be replayed")
    responses, outcomes = await load_recording(mm, run_id)
    spec = AgentSpec.model_validate(original.config["agent_spec"])
    return await mm.run(
        spec,
        original.task,
        original.input,
        label=f"safe replay of {run_id}",
        kind="replay",
        parent_run_id=run_id,
        provider=RecordedProvider(responses, name=f"replay:{spec.model}"),
        replay_outcomes=outcomes,
        wait=wait,
    )


async def rerun(mm: MindMesh, run_id: str, overrides: RunOverrides | None = None, *, wait: bool = True) -> Run:
    original = await mm.repos.runs.get(run_id)
    stored = AgentSpec.model_validate(original.config["agent_spec"])
    # Prefer the currently registered agent definition (it may include fixes);
    # fall back to the spec recorded with the original run.
    base = mm.agents.get(stored.name, stored)
    if original.config.get("overrides"):
        prior = RunOverrides.model_validate(original.config["overrides"])
        merged = prior.model_dump(exclude_none=True)
        merged.update(overrides.model_dump(exclude_none=True) if overrides else {})
        overrides = RunOverrides.model_validate(merged)
    return await mm.run(
        base,
        original.task,
        original.input,
        overrides=overrides,
        label=f"rerun of {run_id}",
        kind="rerun",
        parent_run_id=run_id,
        workflow_run_id=None,
        wait=wait,
    )
