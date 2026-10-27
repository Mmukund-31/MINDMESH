"""Model-call faults (timeouts, retry classification, cancellation) and crash recovery that must
never repeat a side effect. Crashes are injected by cancelling the run task the way a process
shutdown would: the run stays RUNNING and is recovered from the persisted checkpoint + events."""

import asyncio
import time

import pytest

from mindmesh import AgentSpec, Limits
from mindmesh.core.errors import ModelProviderError
from mindmesh.core.types import ModelResponse, PolicyEffect, PolicyRuleIn
from mindmesh.models.scripted import ScriptedProvider
from mindmesh.runtime.agent import AgentRunner


class FnProvider:
    """A provider whose behaviour per call is a coroutine function (sleep, raise, answer)."""

    def __init__(self, name, fn):
        self.name, self.fn, self.calls = name, fn, 0

    async def generate(self, request):
        self.calls += 1
        out = await self.fn(self.calls, request)
        return ModelResponse(text=out, model=self.name, tokens_in=1, tokens_out=1)


def agent_with(mm, name, provider, tools=(), **kw):
    spec = AgentSpec(name=name, tools=list(tools), model=f"test:{name}", **kw)
    mm.register_provider_instance(spec.model, provider)
    return mm.agent(spec)


FINAL = '{"type": "final_answer", "thought": "", "answer": "ok"}'

# --------------------------------------------------------------------------- model faults


async def test_model_timeout_is_retried_then_fails(mm):
    async def slow(n, req):
        await asyncio.sleep(5)
        return FINAL

    agent_with(mm, "slow", FnProvider("slow", slow), limits=Limits(model_timeout_s=0.1, max_retries=2,
                                                                     backoff_base_s=0))
    t0 = time.monotonic()
    run = await mm.run("slow", "t")
    assert time.monotonic() - t0 < 3
    assert run.status == "failed" and "exceeded" in run.error
    fails = await mm.repos.events.list(run.id, types=["model.failed"])
    assert [f.payload["kind"] for f in fails] == ["timeout"] * 3
    assert [f.payload["will_retry"] for f in fails] == [True, True, False]


async def test_transient_provider_error_recovers(mm):
    async def flaky(n, req):
        if n == 1:
            raise ModelProviderError("HTTP 503", retryable=True, status=503)
        return FINAL

    p = FnProvider("flaky", flaky)
    agent_with(mm, "flaky", p, limits=Limits(backoff_base_s=0))
    run = await mm.run("flaky", "t")
    assert run.status == "succeeded" and p.calls == 2
    (fail,) = await mm.repos.events.list(run.id, types=["model.failed"])
    assert fail.payload["status"] == 503 and fail.payload["will_retry"] is True


async def test_permanent_provider_error_is_not_retried(mm):
    async def missing(n, req):
        raise ModelProviderError("HTTP 404: model 'nope' not found", retryable=False, status=404)

    p = FnProvider("missing", missing)
    agent_with(mm, "missing", p, limits=Limits(max_retries=3, backoff_base_s=0))
    run = await mm.run("missing", "t")
    assert run.status == "failed" and "404" in run.error and p.calls == 1


async def test_cancel_interrupts_an_inflight_model_call(mm):
    entered = asyncio.Event()

    async def hang(n, req):
        entered.set()
        await asyncio.sleep(60)
        return FINAL

    agent_with(mm, "hang", FnProvider("hang", hang), limits=Limits(model_timeout_s=60))
    run = await mm.run("hang", "t", wait=False)
    await entered.wait()
    t0 = time.monotonic()
    cancelled = await mm.cancel(run.id)
    assert cancelled.status == "cancelled" and time.monotonic() - t0 < 3


async def test_cancel_flag_from_another_process_is_seen_during_model_call(mm):
    entered = asyncio.Event()

    async def hang(n, req):
        entered.set()
        await asyncio.sleep(60)
        return FINAL

    agent_with(mm, "hang2", FnProvider("hang2", hang), limits=Limits(model_timeout_s=60))
    run = await mm.run("hang2", "t", wait=False)
    await entered.wait()
    await mm.repos.runs.update(run.id, cancel_requested=True)  # what a second API worker would do
    done = await mm.wait(run.id, timeout=5)
    assert done.status == "cancelled"


async def test_shutdown_leaves_run_recoverable(mm):
    entered = asyncio.Event()

    async def hang_once(n, req):
        if n == 1:
            entered.set()
            await asyncio.sleep(60)
        return FINAL

    agent_with(mm, "sd", FnProvider("sd", hang_once))
    run = await mm.run("sd", "t", wait=False)
    await entered.wait()
    task, _ = mm._shared.active[run.id]
    task.cancel()  # process shutdown, not a cancel request
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await mm.repos.runs.get(run.id)).status == "running"
    recovered = await mm.resume(run.id)
    assert recovered.status == "succeeded"


# --------------------------------------------------------------------------- crash recovery


def pay_agent(mm, ledger, gate: asyncio.Event | None = None, *, answer_after=1, paid: asyncio.Event | None = None):
    """An agent that pays once, then answers with what it saw."""

    @mm.tool("pay", side_effect=True)
    async def pay(amount: float) -> dict:
        ledger.append(amount)
        if paid is not None:
            paid.set()
        if gate is not None:
            await gate.wait()  # the crash happens while the side effect is "in flight"
        return {"paid": amount}

    def brain(req):
        if len(req.history) < answer_after:
            return {"type": "tool_call", "tool": "pay", "args": {"amount": 10.0}}
        last = req.history[-1]["outcome"]
        return {"type": "final_answer", "answer": f"{last['status']}:{last.get('error') or last.get('result')}"}

    spec = AgentSpec(name="payer", tools=["pay"], model="scripted:payer", limits=Limits(backoff_base_s=0))
    mm.register_provider_instance(spec.model, ScriptedProvider("payer", brain))
    return mm.agent(spec)


async def crash_run(mm, run_id):
    task, _ = mm._shared.active[run_id]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_interrupted_side_effect_is_not_reexecuted(mm):
    ledger, gate = [], asyncio.Event()
    paid = asyncio.Event()
    pay_agent(mm, ledger, gate, paid=paid)
    run = await mm.run("payer", "pay", wait=False)
    await paid.wait()
    await crash_run(mm, run.id)

    recovered = await mm.resume(run.id)
    assert ledger == [10.0], "the payment must not be repeated"
    assert recovered.status == "succeeded" and recovered.result["answer"].startswith("error:pay was interrupted")
    (resumed,) = await mm.repos.events.list(run.id, types=["run.resumed"])
    assert resumed.payload["inflight"] == "side_effect_unknown"
    assert await mm.repos.events.list(run.id, types=["guard.triggered"])
    assert recovered.tool_calls == 1


async def test_interrupted_side_effect_still_counts_toward_policy_limits(mm):
    ledger, gate = [], asyncio.Event()
    paid = asyncio.Event()
    pay_agent(mm, ledger, gate, answer_after=2, paid=paid)  # the brain tries to pay again after recovery
    await mm.add_policy(PolicyRuleIn(name="once", effect=PolicyEffect.DENY, tools=["pay"], max_calls_per_run=1))
    run = await mm.run("payer", "pay", wait=False)
    await paid.wait()
    await crash_run(mm, run.id)
    recovered = await mm.resume(run.id)
    assert ledger == [10.0]
    assert recovered.result["answer"].startswith("blocked")


async def test_completed_tool_result_is_reused_after_crash(mm, monkeypatch):
    ledger = []
    pay_agent(mm, ledger)
    real = AgentRunner._finish_step

    async def crash_before_step_finished(self, state, step, span, action, outcome):
        if not getattr(self, "_crashed", False):
            self._crashed = True
            raise asyncio.CancelledError  # dies after tool.finished, before step.finished / checkpoint
        return await real(self, state, step, span, action, outcome)

    monkeypatch.setattr(AgentRunner, "_finish_step", crash_before_step_finished)
    run = await mm.run("payer", "pay", wait=False)
    with pytest.raises(asyncio.CancelledError):
        await mm._shared.active[run.id][0]
    monkeypatch.setattr(AgentRunner, "_finish_step", real)

    recovered = await mm.resume(run.id)
    assert ledger == [10.0]
    assert recovered.result["answer"] == "ok:{'paid': 10.0}"
    (resumed,) = await mm.repos.events.list(run.id, types=["run.resumed"])
    assert resumed.payload["inflight"] == "tool_result_recorded"
    calls = await mm.repos.events.list(run.id, types=["model.called"])
    assert recovered.tokens_in == sum(c.payload["tokens_in"] for c in calls), "interrupted step's usage was lost"


async def test_crash_after_approval_request_restores_the_pause(mm, monkeypatch):
    ledger = []
    pay_agent(mm, ledger)
    await mm.add_policy(PolicyRuleIn(name="gate", effect=PolicyEffect.REQUIRE_APPROVAL, tools=["pay"]))
    real = AgentRunner._checkpoint

    async def crash_on_pause(self, state):
        if state.pending:
            raise asyncio.CancelledError
        return await real(self, state)

    monkeypatch.setattr(AgentRunner, "_checkpoint", crash_on_pause)
    run = await mm.run("payer", "pay", wait=False)
    with pytest.raises(asyncio.CancelledError):
        await mm._shared.active[run.id][0]
    monkeypatch.setattr(AgentRunner, "_checkpoint", real)
    assert (await mm.repos.runs.get(run.id)).status == "running"

    paused = await mm.resume(run.id)
    assert paused.status == "waiting_approval"
    (appr,) = await mm.repos.approvals.list(run_id=run.id)  # no duplicate approval was created
    _, done = await mm.resolve_approval(appr.id, True)
    assert done.status == "succeeded" and ledger == [10.0]


async def test_crash_after_final_answer_step_finishes_without_new_model_call(mm, monkeypatch):
    ledger = []
    pay_agent(mm, ledger)
    real = AgentRunner._terminate

    async def crash_on_success(self, dst, state, **kw):
        if dst.value == "succeeded" and not getattr(self, "_crashed", False):
            self._crashed = True
            raise asyncio.CancelledError
        return await real(self, dst, state, **kw)

    monkeypatch.setattr(AgentRunner, "_terminate", crash_on_success)
    run = await mm.run("payer", "pay", wait=False)
    with pytest.raises(asyncio.CancelledError):
        await mm._shared.active[run.id][0]
    monkeypatch.setattr(AgentRunner, "_terminate", real)
    model_calls = len(await mm.repos.events.list(run.id, types=["model.called"]))

    recovered = await mm.resume(run.id)
    assert recovered.status == "succeeded" and ledger == [10.0]
    assert len(await mm.repos.events.list(run.id, types=["model.called"])) == model_calls


# --------------------------------------------------------------------------- replay against persisted events


async def test_replay_of_recovered_run_uses_last_attempt_of_redone_step(mm):
    entered = asyncio.Event()
    ledger = []

    @mm.tool("pay", side_effect=True)
    async def pay(amount: float) -> dict:
        ledger.append(amount)
        return {"paid": amount}

    async def hang_then_pay(n, req):
        if n == 1:
            entered.set()
            await asyncio.sleep(60)
        if not req.history:
            return '{"type": "tool_call", "thought": "", "tool": "pay", "args": {"amount": 5.0}}'
        return FINAL

    agent_with(mm, "rp", FnProvider("rp", hang_then_pay), tools=["pay"])
    run = await mm.run("rp", "t", wait=False)
    await entered.wait()
    await crash_run(mm, run.id)
    recovered = await mm.resume(run.id)
    assert recovered.status == "succeeded" and ledger == [5.0]

    replay = await mm.replay(run.id)
    assert replay.status == "succeeded" and replay.result == recovered.result
    assert ledger == [5.0]
    assert not await mm.repos.events.list(replay.id, types=["replay.diverged"])


async def test_replay_detects_a_tampered_recording(mm):
    ledger = []
    pay_agent(mm, ledger)
    run = await mm.run("payer", "pay")
    (call,) = [e for e in await mm.repos.events.list(run.id, types=["model.called"]) if e.step == 1]
    from mindmesh.storage.orm import EventRow

    async with mm.db.session() as s:
        row = await s.get(EventRow, call.id)
        row.payload = {**row.payload,
                       "response": '{"type": "tool_call", "thought": "", "tool": "pay", "args": {"amount": 999.0}}'}
    replay = await mm.replay(run.id)
    (div,) = await mm.repos.events.list(replay.id, types=["replay.diverged"])
    assert div.payload["args"] == {"amount": 999.0} and div.payload["recorded_args"] == {"amount": 10.0}
    assert ledger == [10.0]


# --------------------------------------------------------------------------- claims checked against tool results


async def test_final_answer_claiming_an_action_that_never_ran_is_rejected(mm):
    from mindmesh import ClaimCheck

    ledger = []

    @mm.tool("pay", side_effect=True)
    async def pay(amount: float) -> dict:
        ledger.append(amount)
        return {"paid": amount}

    def lazy(req):  # like a small model: claims success first, acts only when told
        if not req.history and len(req.messages) == 2:
            return {"type": "final_answer", "answer": "APPROVED: paid"}
        if not req.history:
            return {"type": "tool_call", "tool": "pay", "args": {"amount": 3.0}}
        return {"type": "final_answer", "answer": "APPROVED: paid 3"}

    spec = AgentSpec(name="lazy", tools=["pay"], model="scripted:lazy",
                     claim_checks=[ClaimCheck(answer_regex="^APPROVED", requires_tool="pay")])
    mm.register_provider_instance(spec.model, ScriptedProvider("lazy", lazy))
    mm.agent(spec)
    run = await mm.run("lazy", "t")
    assert run.status == "succeeded" and run.result["answer"] == "APPROVED: paid 3" and ledger == [3.0]
    (guard,) = await mm.repos.events.list(run.id, types=["guard.triggered"])
    assert guard.payload["guard"] == "unsupported_claim"

    always_lazy = AgentSpec(name="lazy2", tools=["pay"], model="scripted:lazy2", limits=Limits(max_retries=1),
                            claim_checks=[ClaimCheck(answer_regex="^APPROVED", requires_tool="pay")])
    mm.register_provider_instance(always_lazy.model, ScriptedProvider(
        "lazy2", lambda req: {"type": "final_answer", "answer": "APPROVED"}))
    mm.agent(always_lazy)
    run2 = await mm.run("lazy2", "t")
    assert run2.status == "failed" and "pay has not succeeded" in run2.error and ledger == [3.0]
