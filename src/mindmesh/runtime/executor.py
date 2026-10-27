"""ToolExecutor: the only code path that can run a tool.

Order of checks for every proposed call (each produces events):
    registry lookup -> strict argument validation -> repeated-failure guard
    -> tool-call budget -> policy decision (allow / deny / require_approval)
    -> execution with timeout + bounded retries (transient errors only)

In *replay* mode the executor never touches the tool: it returns the outcome
recorded in the original run for the same step.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from dataclasses import dataclass, field
from typing import Any

from ..core.errors import ToolArgumentError, TransientToolError
from ..core.events import EventLog, EventType
from ..core.ids import new_id
from ..core.types import AgentSpec, PolicyDecision, PolicyEffect, ToolCallAction
from ..policy.engine import PolicyEngine
from ..policy.tools import ToolContext, ToolRegistry
from ..storage.repositories.policies import ApprovalRepo


@dataclass
class ToolOutcome:
    status: str  # ok | error | blocked | pending_approval | invalid_args
    result: Any = None
    error: str | None = None
    decision: PolicyDecision | None = None
    approval_id: str | None = None
    attempts: int = 0
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"status": self.status, "attempts": self.attempts}
        if self.result is not None:
            d["result"] = self.result
        if self.error:
            d["error"] = self.error
        if self.decision:
            d["policy"] = self.decision.model_dump(mode="json")
        if self.approval_id:
            d["approval_id"] = self.approval_id
        return d


@dataclass
class ExecState:
    tool_calls: int = 0
    calls_by_tool: dict[str, int] = field(default_factory=dict)
    failures: dict[str, int] = field(default_factory=dict)
    injected: dict[str, int] = field(default_factory=dict)  # injected faults already served, per tool


def call_signature(tool: str, args: dict[str, Any]) -> str:
    return f"{tool}:{json.dumps(args, sort_keys=True, default=str)}"


def _jsonable_result(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    try:
        json.dumps(value, default=str)
        return value
    except (TypeError, ValueError):
        return repr(value)


class ToolExecutor:
    def __init__(
        self,
        *,
        registry: ToolRegistry,
        policy: PolicyEngine,
        approvals: ApprovalRepo,
        events: EventLog,
        spec: AgentSpec,
        run_id: str,
        project_id: str,
        memory: Any = None,
        replay_outcomes: dict[int, dict[str, Any]] | None = None,
        faults: dict[str, int] | None = None,
    ):
        self.registry = registry
        self.policy = policy
        self.approvals = approvals
        self.events = events
        self.spec = spec
        self.run_id = run_id
        self.project_id = project_id
        self.memory = memory
        self.replay_outcomes = replay_outcomes
        self.faults = faults or {}

    async def execute(
        self, call: ToolCallAction, *, step: int, span: str, state: ExecState, approved: bool = False
    ) -> ToolOutcome:
        tool = self.registry.get(call.tool)
        if tool is None:
            return await self._blocked(
                call, step, span, PolicyDecision(effect=PolicyEffect.DENY, reason=f"unknown tool '{call.tool}'")
            )
        try:
            args = tool.validate(call.args)
        except ToolArgumentError as e:
            await self.events.emit(
                EventType.TOOL_FAILED,
                {"tool": call.tool, "args": call.args, "error": str(e), "kind": "invalid_args"},
                step=step,
                parent_span_id=span,
            )
            state.failures[call_signature(call.tool, call.args)] = state.failures.get(call_signature(call.tool, call.args), 0) + 1
            return ToolOutcome(status="invalid_args", error=str(e))

        sig = call_signature(call.tool, args)
        if state.failures.get(sig, 0) >= self.spec.limits.repeated_failure_limit:
            await self.events.emit(
                EventType.GUARD_TRIGGERED,
                {"guard": "repeated_failure", "tool": call.tool, "args": args, "failures": state.failures[sig]},
                step=step,
                parent_span_id=span,
            )
            return await self._blocked(
                call,
                step,
                span,
                PolicyDecision(
                    effect=PolicyEffect.DENY,
                    rule_name="guard.repeated_failure",
                    reason=f"identical call already failed {state.failures[sig]}x; change approach",
                ),
            )
        if state.tool_calls >= self.spec.limits.max_tool_calls:
            await self.events.emit(
                EventType.BUDGET_EXCEEDED, {"budget": "max_tool_calls", "limit": self.spec.limits.max_tool_calls},
                step=step, parent_span_id=span,
            )
            return await self._blocked(
                call, step, span,
                PolicyDecision(effect=PolicyEffect.DENY, rule_name="budget.max_tool_calls", reason="tool-call budget exhausted"),
            )

        if self.spec.enforce_policies:
            decision = self.policy.evaluate(
                call.tool,
                args,
                agent=self.spec.name,
                role=self.spec.role,
                allowed_tools=self.spec.tools,
                calls_so_far=state.calls_by_tool,
            )
            if approved and decision.effect == PolicyEffect.REQUIRE_APPROVAL:
                decision = PolicyDecision(
                    effect=PolicyEffect.ALLOW, rule_id=decision.rule_id, rule_name=decision.rule_name,
                    reason="approved by human reviewer",
                )
        else:
            decision = PolicyDecision(effect=PolicyEffect.ALLOW, reason="policy enforcement disabled for this agent")
        await self.events.emit(
            EventType.POLICY_DECISION,
            {"tool": call.tool, "args": args, **decision.model_dump(mode="json")},
            step=step,
            parent_span_id=span,
        )
        if decision.effect == PolicyEffect.DENY:
            return ToolOutcome(status="blocked", decision=decision, error=f"blocked by policy: {decision.reason}")
        if decision.effect == PolicyEffect.REQUIRE_APPROVAL:
            if self.replay_outcomes is not None:
                recorded = self.replay_outcomes.get(step)
                if recorded and recorded.get("status") == "ok":
                    pass  # original run was approved; fall through to recorded result
                else:
                    return ToolOutcome(status="pending_approval", decision=decision, error="approval required (replay)")
            else:
                appr = await self.approvals.create(self.run_id, step, call.tool, args, decision.reason)
                await self.events.emit(
                    EventType.APPROVAL_REQUESTED,
                    {"approval_id": appr.id, "tool": call.tool, "args": args, "reason": decision.reason},
                    step=step,
                    parent_span_id=span,
                )
                return ToolOutcome(status="pending_approval", decision=decision, approval_id=appr.id)

        state.tool_calls += 1
        state.calls_by_tool[call.tool] = state.calls_by_tool.get(call.tool, 0) + 1
        if self.replay_outcomes is not None:
            return await self._replayed(call, args, step, span, decision)
        outcome = await self._run_with_retries(tool, args, step=step, span=span, state=state)
        outcome.decision = decision
        if outcome.status != "ok":
            state.failures[sig] = state.failures.get(sig, 0) + 1
        return outcome

    # ------------------------------------------------------------------ internals

    async def _blocked(self, call: ToolCallAction, step: int, span: str, decision: PolicyDecision) -> ToolOutcome:
        await self.events.emit(
            EventType.POLICY_DECISION,
            {"tool": call.tool, "args": call.args, **decision.model_dump(mode="json")},
            step=step,
            parent_span_id=span,
        )
        return ToolOutcome(status="blocked", decision=decision, error=f"blocked: {decision.reason}")

    async def _replayed(self, call, args, step, span, decision) -> ToolOutcome:
        recorded = self.replay_outcomes.get(step) if self.replay_outcomes else None
        tool_span = new_id("span")
        await self.events.emit(
            EventType.TOOL_STARTED, {"tool": call.tool, "args": args, "replayed": True},
            step=step, span_id=tool_span, parent_span_id=span,
        )
        rec_action = (recorded or {}).get("recorded_action") or {}
        if rec_action and (rec_action.get("tool") != call.tool or (rec_action.get("args") or {}) != call.args):
            await self.events.emit(
                EventType.REPLAY_DIVERGED,
                {"step": step, "tool": call.tool, "args": call.args, "recorded_tool": rec_action.get("tool"),
                 "recorded_args": rec_action.get("args"), "reason": "replayed action differs from the recording"},
                step=step, parent_span_id=span,
            )
            return ToolOutcome(status="error", error="replay diverged: action differs from the recording",
                               decision=decision)
        if not recorded or recorded.get("status") not in ("ok", "error"):
            await self.events.emit(
                EventType.REPLAY_DIVERGED,
                {"step": step, "tool": call.tool, "reason": "no recorded tool result for this step"},
                step=step, parent_span_id=span,
            )
            return ToolOutcome(status="error", error="replay diverged: no recorded result", decision=decision)
        await self.events.emit(
            EventType.TOOL_FINISHED if recorded["status"] == "ok" else EventType.TOOL_FAILED,
            {"tool": call.tool, "result": recorded.get("result"), "error": recorded.get("error"), "replayed": True},
            step=step, span_id=tool_span, parent_span_id=span, duration_ms=0.0,
        )
        return ToolOutcome(
            status=recorded["status"], result=recorded.get("result"), error=recorded.get("error"),
            decision=decision, attempts=1,
        )

    def _inject_fault(self, tool_name: str, state: ExecState) -> None:
        served = state.injected.get(tool_name, 0)
        if served < self.faults.get(tool_name, 0):
            state.injected[tool_name] = served + 1
            raise TransientToolError(f"{tool_name} upstream unavailable (503, injected fault {served + 1}/"
                                     f"{self.faults[tool_name]})")

    async def _run_with_retries(
        self, tool, args: dict[str, Any], *, step: int, span: str, state: ExecState
    ) -> ToolOutcome:
        limits = self.spec.limits
        timeout = tool.timeout_s or limits.tool_timeout_s
        tool_span = new_id("span")
        await self.events.emit(
            EventType.TOOL_STARTED,
            {"tool": tool.name, "args": args, "side_effect": tool.side_effect, "timeout_s": timeout},
            step=step,
            span_id=tool_span,
            parent_span_id=span,
        )
        attempt = 0
        t0 = time.perf_counter()
        while True:
            attempt += 1
            injected = False
            try:
                try:
                    self._inject_fault(tool.name, state)
                except TransientToolError:
                    injected = True
                    raise
                kwargs = dict(args)
                if tool.wants_ctx:
                    kwargs["ctx"] = ToolContext(
                        run_id=self.run_id, project_id=self.project_id, agent=self.spec.name, step=step,
                        memory=self.memory,
                    )
                async with asyncio.timeout(timeout):
                    if inspect.iscoroutinefunction(tool.fn):
                        result = await tool.fn(**kwargs)
                    else:
                        result = await asyncio.to_thread(tool.fn, **kwargs)
                dur = (time.perf_counter() - t0) * 1000
                result = _jsonable_result(result)
                await self.events.emit(
                    EventType.TOOL_FINISHED,
                    {"tool": tool.name, "result": result, "attempts": attempt},
                    step=step, span_id=tool_span, parent_span_id=span, duration_ms=dur,
                )
                return ToolOutcome(status="ok", result=result, attempts=attempt, duration_ms=dur)
            except (TimeoutError, TransientToolError) as e:
                err = f"timeout after {timeout}s" if isinstance(e, TimeoutError) else f"transient error: {e}"
                retryable = not tool.side_effect or isinstance(e, TransientToolError)
                if attempt <= limits.max_retries and retryable:
                    delay = limits.backoff_base_s * (2 ** (attempt - 1))
                    await self.events.emit(
                        EventType.TOOL_RETRY,
                        {"tool": tool.name, "attempt": attempt, "error": err, "backoff_s": delay, "injected": injected},
                        step=step, parent_span_id=tool_span,
                    )
                    await asyncio.sleep(delay)
                    continue
                return await self._fail(tool.name, err, attempt, step, span, tool_span, t0, injected)
            except Exception as e:  # tool bug or permanent failure: never retried
                return await self._fail(tool.name, f"{type(e).__name__}: {e}", attempt, step, span, tool_span, t0, False)

    async def _fail(self, name, err, attempt, step, span, tool_span, t0, injected: bool) -> ToolOutcome:
        dur = (time.perf_counter() - t0) * 1000
        await self.events.emit(
            EventType.TOOL_FAILED,
            {"tool": name, "error": err, "attempts": attempt, "injected": injected},
            step=step, span_id=tool_span, parent_span_id=span, duration_ms=dur,
        )
        return ToolOutcome(status="error", error=err, attempts=attempt, duration_ms=dur)
