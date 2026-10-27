"""The agent execution runtime.

One :class:`AgentRunner` drives one run through an explicit state machine::

    PENDING -> RUNNING <-> WAITING_APPROVAL -> SUCCEEDED | FAILED | CANCELLED

Each step: assemble context (receipt) -> model call (bounded retries, output
repair) -> policy-checked tool execution -> event log -> checkpoint. Runs can be
paused for human approval, resumed from the latest checkpoint (also after a
crash), cancelled cooperatively, and replayed from recorded outputs.

Crash recovery reconciles the interrupted step with the persisted event log
before continuing: a tool call the log shows already ran is never executed a
second time, and a side-effecting call whose outcome is unknown is reported to
the model as failed instead of being repeated.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

from ..core import clock
from ..core.errors import BudgetExceeded, ModelOutputError, ModelProviderError, RunCancelled, UnsupportedClaim
from ..core.events import EventLog, EventType
from ..core.ids import new_id
from ..core.state import TERMINAL_RUN, RunStatus, transition
from ..core.types import (
    AgentSpec,
    ContextItem,
    ContextReceipt,
    FinalAnswerAction,
    MemoryCreate,
    MemoryKind,
    Message,
    ModelResponse,
    Provenance,
    Run,
    ToolCallAction,
)
from ..models.base import GenerationRequest, ModelProvider, estimate_tokens
from ..policy.engine import PolicyEngine
from .executor import ExecState, ToolExecutor, ToolOutcome, call_signature
from .prompting import ACTION_SCHEMA, build_messages, parse_action

if TYPE_CHECKING:
    from ..sdk import MindMesh

MAX_LOGGED_MESSAGE_CHARS = 6000
CANCEL_POLL_S = 0.5  # how often an in-flight model call checks for a cancel request


@dataclass
class RunState:
    step: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)
    exec: dict[str, Any] = field(default_factory=lambda: asdict(ExecState()))
    tokens_in: int = 0
    tokens_out: int = 0
    pending: dict[str, Any] | None = None
    evidence: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RunState:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class RunOptions:
    provider: ModelProvider | None = None
    replay_outcomes: dict[int, dict[str, Any]] | None = None
    evidence: list[ContextItem] = field(default_factory=list)


class AgentRunner:
    def __init__(self, mm: MindMesh, spec: AgentSpec, run: Run, options: RunOptions | None = None):
        self.mm = mm
        self.spec = spec
        self.run = run
        self.opts = options or RunOptions()
        self.repos = mm.repos
        self.events: EventLog | None = None
        self.cancel_event = asyncio.Event()
        self.provider: ModelProvider = self.opts.provider or mm.resolve_model(spec.model)

    @property
    def replaying(self) -> bool:
        return self.opts.replay_outcomes is not None

    # ------------------------------------------------------------------ entry points

    async def start(self) -> Run:
        self.events = EventLog(self.repos.events, self.run.id, redactor=self.mm.redactor)
        await self.events.emit(
            EventType.RUN_CREATED,
            {
                "agent": self.spec.name,
                "role": self.spec.role,
                "task": self.run.task,
                "input": self.run.input,
                "model": self.provider.name,
                "kind": self.run.kind,
                "parent_run_id": self.run.parent_run_id,
                "config": self.run.config,
            },
            span_id=self.events.root_span,
        )
        state = RunState(evidence=[e.model_dump(mode="json") for e in self.opts.evidence])
        await self._set_status(RunStatus.RUNNING, started_at=clock.now())
        return await self._drive(state)

    async def resume(self) -> Run:
        """Continue after an approval decision, or recover a run interrupted mid-flight."""
        self.events = await EventLog.resume(self.repos.events, self.run.id, redactor=self.mm.redactor)
        ckpt = await self.repos.runs.latest_checkpoint(self.run.id)
        state = RunState.from_dict(ckpt["state"]) if ckpt else RunState()
        status = RunStatus(self.run.status)
        if status == RunStatus.WAITING_APPROVAL:
            pending = state.pending or {}
            approval = await self.repos.approvals.get(pending["approval_id"])
            if approval.status == "pending":
                raise ValueError(f"approval {approval.id} is still pending")
            await self._set_status(RunStatus.RUNNING, reason=f"approval {approval.status}")
            await self.events.emit(
                EventType.APPROVAL_RESOLVED,
                {"approval_id": approval.id, "status": approval.status, "resolver": approval.resolver,
                 "note": approval.note},
                step=pending["step"], parent_span_id=pending["span"],
            )
            action = ToolCallAction.model_validate(pending["action"])
            if approval.status == "approved":
                exec_state = ExecState(**state.exec)
                outcome = await self._executor().execute(
                    action, step=pending["step"], span=pending["span"], state=exec_state, approved=True
                )
                state.exec = asdict(exec_state)
            else:
                outcome = ToolOutcome(
                    status="blocked",
                    error=f"rejected by human reviewer {approval.resolver or ''}: {approval.note or 'no reason given'}",
                )
            state.pending = None
            await self._finish_step(state, pending["step"], pending["span"], action, outcome)
        elif status == RunStatus.RUNNING:
            recovery = await self._recover_inflight(state, ckpt["event_seq"] if ckpt else 0)
            await self.events.emit(
                EventType.RUN_RESUMED, {"recovered": True, "from_step": state.step, "inflight": recovery},
                span_id=self.events.root_span,
            )
        elif status == RunStatus.PENDING:
            return await self.start()
        else:
            raise ValueError(f"cannot resume a {status.value} run")
        return await self._drive(state)

    # ------------------------------------------------------------------ main loop

    async def _drive(self, state: RunState) -> Run:
        try:
            await self._loop(state)
        except RunCancelled as e:
            await self._terminate(RunStatus.CANCELLED, state, error=str(e) or "cancelled")
        except BudgetExceeded as e:
            await self.events.emit(EventType.BUDGET_EXCEEDED, {"reason": str(e)}, span_id=self.events.root_span)
            await self._terminate(RunStatus.FAILED, state, error=f"budget exceeded: {e}")
        except asyncio.CancelledError:
            # A cancel request that had to interrupt the task is recorded; any other task cancellation
            # (process shutdown) leaves the run RUNNING so it can be recovered from its checkpoint.
            if self.cancel_event.is_set():
                await self._terminate(RunStatus.CANCELLED, state, error="cancelled by request")
            raise
        except Exception as e:  # noqa: BLE001 - any crash must end in a recorded terminal state
            await self._terminate(RunStatus.FAILED, state, error=f"{type(e).__name__}: {e}")
        return self.run

    async def _loop(self, state: RunState) -> None:
        limits = self.spec.limits
        deadline = time.monotonic() + limits.timeout_s
        while True:
            if RunStatus(self.run.status) != RunStatus.RUNNING:
                return  # paused for approval or terminated
            await self._check_cancel()
            if state.step >= limits.max_steps:
                raise BudgetExceeded(f"max_steps={limits.max_steps} reached without a final answer")
            if time.monotonic() > deadline:
                raise BudgetExceeded(f"timeout_s={limits.timeout_s} exceeded")
            step = state.step + 1
            span = new_id("span")
            await self.events.emit(EventType.STEP_STARTED, {"step": step}, step=step, span_id=span)
            receipt = await self._assemble_context(step, state)
            await self.events.emit(
                EventType.CONTEXT_ASSEMBLED, receipt.model_dump(mode="json"), step=step, parent_span_id=span
            )
            action = await self._decide(step, span, state, receipt, deadline)

            if isinstance(action, FinalAnswerAction):
                state.history.append({"step": step, "action": action.model_dump(), "outcome": {"status": "final"}})
                state.step = step
                await self.events.emit(
                    EventType.STEP_FINISHED,
                    {"action": action.model_dump(), "outcome": {"status": "final"}},
                    step=step, span_id=span,
                )
                await self._checkpoint(state)
                await self._terminate(
                    RunStatus.SUCCEEDED, state,
                    result={"answer": action.answer, "evidence": action.evidence, "thought": action.thought},
                )
                return

            exec_state = ExecState(**state.exec)
            outcome = await self._executor().execute(action, step=step, span=span, state=exec_state)
            state.exec = asdict(exec_state)
            if outcome.status == "pending_approval" and not self.replaying:
                state.pending = {
                    "approval_id": outcome.approval_id, "action": action.model_dump(), "step": step, "span": span,
                }
                await self._checkpoint(state)
                await self._set_status(RunStatus.WAITING_APPROVAL, reason=outcome.decision.reason if outcome.decision else None)
                return
            if outcome.status == "pending_approval":
                outcome = ToolOutcome(status="blocked", decision=outcome.decision, error="approval required (replay)")
            await self._finish_step(state, step, span, action, outcome)

    async def _finish_step(self, state: RunState, step: int, span: str, action: ToolCallAction, outcome: ToolOutcome):
        state.history.append({"step": step, "action": action.model_dump(), "outcome": outcome.to_dict()})
        state.step = step
        await self.events.emit(
            EventType.STEP_FINISHED,
            {"action": action.model_dump(), "outcome": outcome.to_dict()},
            step=step, span_id=span,
        )
        await self._checkpoint(state)

    # ------------------------------------------------------------------ pieces

    def _executor(self) -> ToolExecutor:
        return ToolExecutor(
            registry=self.mm.tools,
            policy=self._policy,
            approvals=self.repos.approvals,
            events=self.events,
            spec=self.spec,
            run_id=self.run.id,
            project_id=self.mm.project_id,
            memory=self.mm.memory,
            replay_outcomes=self.opts.replay_outcomes,
        )

    @property
    def _policy(self) -> PolicyEngine:
        return self.mm._policy_cache  # refreshed by MindMesh before each start/resume

    async def _assemble_context(self, step: int, state: RunState) -> ContextReceipt:
        query = self.run.task
        if self.run.input:
            query += " " + " ".join(f"{k} {v}" for k, v in self.run.input.items() if isinstance(v, str | int | float))
        if state.history:
            last = state.history[-1]
            query += " " + json.dumps(last["outcome"].get("result") or "", default=str)[:500]
        pinned = [
            ContextItem(item_id="task", kind="task", content=f"{self.run.task} {json.dumps(self.run.input, default=str)}",
                        tokens=estimate_tokens(self.run.task) + 4)
        ]
        evidence = [ContextItem.model_validate(e) for e in state.evidence]
        return await self.mm.context.assemble(
            query=query,
            config=self.spec.context,
            scopes=self.spec.memory_scopes,
            run_id=self.run.id,
            step=step,
            pinned=pinned,
            evidence=evidence,
        )

    async def _decide(self, step: int, span: str, state: RunState, receipt: ContextReceipt, deadline: float):
        limits = self.spec.limits
        tools = self.mm.tools.specs(self.spec.tools)
        base = build_messages(
            system_prompt=self.spec.system_prompt,
            task=self.run.task,
            task_input=self.run.input,
            tools=tools,
            context=receipt.included,
            history=state.history,
            redact=self.mm.redactor,
        )
        repair: list = []
        attempt = 0
        while True:
            attempt += 1
            await self._check_cancel()
            req = GenerationRequest(
                messages=base + repair,
                json_schema=ACTION_SCHEMA,
                context=receipt.included,
                history=state.history,
                task=self.run.task,
                task_input=self.run.input,
                tools=[t.json_schema() for t in tools],
                agent=self.spec.name,
                step=step,
            )
            t0 = time.perf_counter()
            try:
                resp: ModelResponse = await self._call_model(req, deadline)
            except (RunCancelled, BudgetExceeded):
                raise
            except Exception as e:  # transport / provider failure
                err = e if isinstance(e, ModelProviderError) else ModelProviderError(
                    f"{type(e).__name__}: {e}", retryable=True)  # unknown provider error: assume transient
                retry = err.retryable and attempt <= limits.max_retries
                backoff = limits.backoff_base_s * 2 ** (attempt - 1)
                await self.events.emit(
                    EventType.MODEL_FAILED,
                    {"error": str(err), "attempt": attempt, "kind": err.kind, "status": err.status,
                     "retryable": err.retryable, "will_retry": retry, "backoff_s": backoff if retry else None,
                     "model": self.provider.name},
                    step=step, parent_span_id=span, duration_ms=(time.perf_counter() - t0) * 1000,
                )
                if retry:
                    await asyncio.sleep(backoff)
                    continue
                raise err from e
            wall_ms = (time.perf_counter() - t0) * 1000
            state.tokens_in += resp.tokens_in
            state.tokens_out += resp.tokens_out
            await self.events.emit(
                EventType.MODEL_CALLED,
                {
                    "model": resp.model,
                    "model_reported": resp.model_reported,
                    "model_digest": resp.model_digest,
                    "request_id": resp.request_id,
                    "stop_reason": resp.stop_reason,
                    "attempt": attempt,
                    "messages": [
                        {"role": m.role, "content": m.content[:MAX_LOGGED_MESSAGE_CHARS]} for m in req.messages
                    ],
                    "response": resp.text,
                    "tokens_in": resp.tokens_in,
                    "tokens_out": resp.tokens_out,
                    "usage_reported": resp.usage_reported,
                    "latency_ms": resp.latency_ms,
                    "wall_ms": wall_ms,
                    "provider_timing_ms": resp.provider_timing_ms,
                },
                step=step, parent_span_id=span, duration_ms=resp.latency_ms,
            )
            if state.tokens_in + state.tokens_out > limits.max_tokens:
                raise BudgetExceeded(f"max_tokens={limits.max_tokens} exceeded")
            try:
                action = parse_action(resp.text)
                self._check_claims(action, state)
                return action
            except ModelOutputError as e:
                if isinstance(e, UnsupportedClaim):
                    await self.events.emit(
                        EventType.GUARD_TRIGGERED, {"guard": "unsupported_claim", "reason": str(e)},
                        step=step, parent_span_id=span,
                    )
                await self.events.emit(
                    EventType.MODEL_FAILED,
                    {"error": str(e), "attempt": attempt, "kind": e.kind, "retryable": True,
                     "will_retry": attempt <= limits.max_retries},
                    step=step, parent_span_id=span,
                )
                if attempt > limits.max_retries:
                    raise
                cut = " It was cut off at the length limit, so do not reason in prose." if resp.stop_reason == "length" else ""
                repair = [
                    Message(role="assistant", content=resp.text[:2000]),
                    Message(role="user",
                            content=f"Your reply was invalid ({e}).{cut} Reply with ONE JSON object only."),
                ]

    def _check_claims(self, action, state: RunState) -> None:
        if not isinstance(action, FinalAnswerAction):
            return
        for c in self.spec.claim_checks:
            if not re.search(c.answer_regex, action.answer):
                continue
            if not any(h["action"].get("tool") == c.requires_tool and h["outcome"].get("status") == "ok"
                       for h in state.history):
                raise UnsupportedClaim(
                    f"the answer matches /{c.answer_regex}/ but {c.requires_tool} has not succeeded in this run. "
                    f"{c.hint}".strip()
                )

    async def _call_model(self, req: GenerationRequest, deadline: float) -> ModelResponse:
        """One provider call, bounded by ``model_timeout_s`` and the run deadline, abandoned on cancel."""
        limits = self.spec.limits
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise BudgetExceeded(f"timeout_s={limits.timeout_s} exceeded")
        budget = min(limits.model_timeout_s, remaining)
        call = asyncio.ensure_future(self.provider.generate(req))
        try:
            async with asyncio.timeout(budget):
                while True:
                    cancelled = asyncio.ensure_future(self.cancel_event.wait())
                    done, _ = await asyncio.wait({call, cancelled}, timeout=CANCEL_POLL_S,
                                                 return_when=asyncio.FIRST_COMPLETED)
                    cancelled.cancel()
                    if call in done:
                        return call.result()
                    await self._check_cancel()  # in-process event, or a cancel flag set by another process
        except TimeoutError:
            if call.done() and not call.cancelled() and call.exception() is not None:
                raise call.exception() from None  # the provider's own timeout error, not ours
            raise ModelProviderError(f"model call exceeded {budget:.1f}s", retryable=True, kind="timeout") from None
        finally:
            if not call.done():
                call.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await call

    async def _recover_inflight(self, state: RunState, after_seq: int) -> str:
        """Reconcile the step that was executing when the run was interrupted with what the event log
        proves happened, so recovery never repeats a side effect. Returns how it was handled."""
        after = await self.repos.events.list(self.run.id, after_seq=after_seq)
        for e in after:  # model calls after the checkpoint were paid for but are missing from its totals
            if e.type == EventType.MODEL_CALLED:
                state.tokens_in += e.payload.get("tokens_in", 0)
                state.tokens_out += e.payload.get("tokens_out", 0)
        if state.history and state.history[-1]["outcome"].get("status") == "final":
            return await self._finish_recorded_final(state)
        step = state.step + 1
        evs = [e for e in after if e.step == step]
        if not evs:
            return "none"
        last = {e.type: e for e in evs}
        span = next((e.span_id for e in evs if e.type == EventType.STEP_STARTED), None) or new_id("span")
        started = last.get(EventType.TOOL_STARTED)

        def count_call(tool: str, ok: bool, args: dict[str, Any]) -> None:
            ex = ExecState(**state.exec)
            ex.tool_calls += 1
            ex.calls_by_tool[tool] = ex.calls_by_tool.get(tool, 0) + 1
            if not ok:
                sig = call_signature(tool, args)
                ex.failures[sig] = ex.failures.get(sig, 0) + 1
            state.exec = asdict(ex)

        if EventType.STEP_FINISHED in last:  # interrupted between step.finished and its checkpoint
            p = last[EventType.STEP_FINISHED].payload
            outcome = p.get("outcome", {})
            if started is not None:
                count_call(started.payload["tool"], outcome.get("status") == "ok", started.payload.get("args", {}))
            state.history.append({"step": step, "action": p["action"], "outcome": outcome})
            state.step = step
            await self._checkpoint(state)
            if outcome.get("status") == "final":
                return await self._finish_recorded_final(state)
            return "step_finished_recorded"

        if EventType.APPROVAL_REQUESTED in last:  # interrupted before the pause was persisted
            p = last[EventType.APPROVAL_REQUESTED].payload
            action = ToolCallAction(tool=p["tool"], args=p.get("args", {}), thought=self._recorded_thought(evs))
            state.pending = {"approval_id": p["approval_id"], "action": action.model_dump(), "step": step,
                             "span": span}
            await self._checkpoint(state)
            await self._set_status(RunStatus.WAITING_APPROVAL, reason="approval requested before interruption")
            return "approval_pending"

        if started is None:
            return "redo_step"  # no tool started yet: repeating the step is safe
        tool, args = started.payload["tool"], started.payload.get("args", {})
        action = ToolCallAction(tool=tool, args=args, thought=self._recorded_thought(evs))
        done = next((e for e in evs if e.type in (EventType.TOOL_FINISHED, EventType.TOOL_FAILED)
                     and e.span_id == started.span_id), None)
        if done is not None:  # the tool completed: reuse its recorded result
            ok = done.type == EventType.TOOL_FINISHED
            outcome = ToolOutcome(status="ok" if ok else "error", result=done.payload.get("result"),
                                  error=done.payload.get("error"), attempts=done.payload.get("attempts", 1))
            count_call(tool, ok, args)
            await self._finish_step(state, step, span, action, outcome)
            return "tool_result_recorded"
        if not started.payload.get("side_effect"):
            return "redo_step"  # an interrupted read-only call is safe to repeat
        await self.events.emit(
            EventType.GUARD_TRIGGERED,
            {"guard": "unsafe_reexecution", "tool": tool, "args": args,
             "reason": "side-effecting call was interrupted; its outcome is unknown"},
            step=step, parent_span_id=span,
        )
        count_call(tool, False, args)  # it may have taken effect, so it counts against per-run limits
        outcome = ToolOutcome(
            status="error", attempts=1,
            error=f"{tool} was interrupted while running; it may or may not have taken effect, so it was NOT "
                  "re-executed. Do not repeat it; escalate so a human can verify.",
        )
        await self._finish_step(state, step, span, action, outcome)
        return "side_effect_unknown"

    async def _finish_recorded_final(self, state: RunState) -> str:
        action = FinalAnswerAction.model_validate(state.history[-1]["action"])
        await self._terminate(RunStatus.SUCCEEDED, state, result={
            "answer": action.answer, "evidence": action.evidence, "thought": action.thought})
        return "final_answer_recorded"

    @staticmethod
    def _recorded_thought(evs: list) -> str:
        for e in reversed(evs):
            if e.type == EventType.MODEL_CALLED:
                try:
                    return parse_action(e.payload.get("response", "")).thought
                except ModelOutputError:
                    return ""
        return ""

    async def _checkpoint(self, state: RunState) -> None:
        await self.repos.runs.save_checkpoint(self.run.id, state.step, self.events.seq + 1, asdict(state))
        await self.events.emit(EventType.CHECKPOINT_SAVED, {"step": state.step}, step=state.step or None)
        self.run = await self.repos.runs.update(
            self.run.id,
            steps=state.step,
            tool_calls=state.exec.get("tool_calls", 0),
            tokens_in=state.tokens_in,
            tokens_out=state.tokens_out,
        )

    async def _check_cancel(self) -> None:
        if self.cancel_event.is_set():
            raise RunCancelled("cancelled by request")
        fresh = await self.repos.runs.get(self.run.id)
        if fresh.cancel_requested:
            raise RunCancelled("cancel requested")

    async def _set_status(self, dst: RunStatus, *, reason: str | None = None, **fields: Any) -> None:
        src = RunStatus(self.run.status)
        transition(src, dst)
        self.run = await self.repos.runs.update(self.run.id, status=dst.value, **fields)
        await self.events.emit(
            EventType.RUN_STATE, {"from": src.value, "to": dst.value, "reason": reason}, span_id=self.events.root_span
        )

    async def _terminate(self, dst: RunStatus, state: RunState, *, result=None, error: str | None = None) -> None:
        if RunStatus(self.run.status) in TERMINAL_RUN:
            return
        await self._set_status(
            dst,
            reason=error,
            result=result,
            error=error,
            ended_at=clock.now(),
            steps=state.step,
            tool_calls=state.exec.get("tool_calls", 0),
            tokens_in=state.tokens_in,
            tokens_out=state.tokens_out,
        )
        if self.spec.remember_outcomes and not self.replaying and self.run.kind != "eval":
            outcome = result["answer"] if result else error
            mem = await self.mm.memory.add(
                MemoryCreate(
                    content=f"Episode: task '{self.run.task[:300]}' ended {dst.value}: {str(outcome)[:500]}",
                    kind=MemoryKind.EPISODE,
                    scope=f"agent:{self.spec.name}",
                    provenance=Provenance(source_type="run", source_ref=self.run.id, created_by=self.spec.name),
                    trust=0.5,
                    importance=0.3,
                ),
                run_id=self.run.id,
            )
            await self.events.emit(EventType.MEMORY_WRITTEN, {"memory_id": mem.id, "kind": "episode"},
                                   span_id=self.events.root_span)
