import asyncio
import json

import pytest

from mindmesh import AgentSpec, Limits, TransientToolError
from mindmesh.core.errors import ModelOutputError
from mindmesh.core.types import PolicyEffect, PolicyRuleIn
from mindmesh.models.scripted import ScriptedProvider
from mindmesh.runtime.prompting import parse_action


def tool_then_answer(tool, args, answer="done"):
    def fn(req):
        if not req.history:
            return {"type": "tool_call", "thought": "", "tool": tool, "args": args}
        last = req.history[-1]["outcome"]
        detail = last.get('result') if last.get('result') is not None else last.get('error')
        return {"type": "final_answer", "answer": f"{answer}:{last['status']}:{detail}"}
    return fn


def make_agent(mm, name, tools, fn, **kw):
    spec = AgentSpec(name=name, tools=tools, model=f"scripted:{name}", **kw)
    mm.register_provider_instance(spec.model, ScriptedProvider(name, fn))
    return mm.agent(spec)


async def test_happy_path_records_events_and_checkpoints(mm):
    @mm.tool()
    async def add(a: int, b: int) -> int:
        return a + b

    make_agent(mm, "calc", ["add"], tool_then_answer("add", {"a": 2, "b": 3}))
    run = await mm.run("calc", "add numbers")
    assert run.status == "succeeded" and run.result["answer"] == "done:ok:5"
    assert run.steps == 2 and run.tool_calls == 1
    types = [e.type for e in await mm.repos.events.list(run.id)]
    for t in ("run.created", "context.assembled", "model.called", "policy.decision", "tool.started",
              "tool.finished", "checkpoint.saved", "step.finished"):
        assert t in types
    seqs = [e.seq for e in await mm.repos.events.list(run.id)]
    assert seqs == list(range(1, len(seqs) + 1))
    assert len(await mm.repos.runs.list_checkpoints(run.id)) == 2


async def test_transient_failures_are_retried_with_bound(mm):
    calls = {"n": 0}

    @mm.tool()
    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise TransientToolError("503")
        return "ok"

    make_agent(mm, "a1", ["flaky"], tool_then_answer("flaky", {}), limits=Limits(max_retries=2, backoff_base_s=0))
    run = await mm.run("a1", "t")
    assert run.result["answer"] == "done:ok:ok" and calls["n"] == 3
    retries = await mm.repos.events.list(run.id, types=["tool.retry"])
    assert len(retries) == 2

    calls["n"] = -10  # needs 13 attempts; only 3 allowed
    run2 = await mm.run("a1", "t")
    assert run2.result["answer"].startswith("done:error")


async def test_permanent_errors_are_not_retried(mm):
    n = {"c": 0}

    @mm.tool()
    def boom() -> str:
        n["c"] += 1
        raise RuntimeError("bad input")

    make_agent(mm, "a2", ["boom"], tool_then_answer("boom", {}), limits=Limits(backoff_base_s=0))
    run = await mm.run("a2", "t")
    assert n["c"] == 1 and "RuntimeError" in run.result["answer"]


async def test_tool_timeout(mm):
    @mm.tool(timeout_s=0.05)
    async def slow() -> str:
        await asyncio.sleep(1)
        return "late"

    make_agent(mm, "a3", ["slow"], tool_then_answer("slow", {}), limits=Limits(max_retries=0))
    run = await mm.run("a3", "t")
    assert "timeout" in run.result["answer"]


async def test_repeated_failure_guard_blocks_identical_calls(mm):
    @mm.tool()
    def fails(x: int) -> str:
        raise ValueError("nope")

    def stubborn(req):
        if len(req.history) < 4:
            return {"type": "tool_call", "tool": "fails", "args": {"x": 1}}
        return {"type": "final_answer", "answer": json.dumps([h["outcome"]["status"] for h in req.history])}

    make_agent(mm, "a4", ["fails"], stubborn, limits=Limits(repeated_failure_limit=2, backoff_base_s=0))
    run = await mm.run("a4", "t")
    assert json.loads(run.result["answer"]) == ["error", "error", "blocked", "blocked"]
    assert await mm.repos.events.list(run.id, types=["guard.triggered"])


async def test_max_steps_budget_fails_run(mm):
    @mm.tool()
    def noop() -> str:
        return "x"

    make_agent(mm, "loop", ["noop"], lambda req: {"type": "tool_call", "tool": "noop", "args": {}},
               limits=Limits(max_steps=3, repeated_failure_limit=99))
    run = await mm.run("loop", "t")
    assert run.status == "failed" and "max_steps" in run.error and run.steps == 3


async def test_token_budget(mm):
    make_agent(mm, "verbose", [], lambda req: {"type": "final_answer", "answer": "x" * 4000},
               limits=Limits(max_tokens=500))
    run = await mm.run("verbose", "t")
    assert run.status == "failed" and "max_tokens" in run.error


async def test_invalid_model_output_is_repaired_then_bounded(mm):
    outputs = iter(["not json at all", '{"type": "final_answer", "answer": "fixed"}'])
    make_agent(mm, "sloppy", [], lambda req: next(outputs))
    run = await mm.run("sloppy", "t")
    assert run.result["answer"] == "fixed"
    assert len(await mm.repos.events.list(run.id, types=["model.failed"])) == 1

    make_agent(mm, "hopeless", [], lambda req: "nope", limits=Limits(max_retries=1))
    run2 = await mm.run("hopeless", "t")
    assert run2.status == "failed" and "ModelOutputError" in run2.error


async def test_invalid_arguments_rejected_before_execution(mm):
    hit = {"n": 0}

    @mm.tool()
    def strict(n: int) -> int:
        hit["n"] += 1
        return n

    make_agent(mm, "a5", ["strict"], tool_then_answer("strict", {"n": "5", "extra": 1}))
    run = await mm.run("a5", "t")
    assert hit["n"] == 0 and run.result["answer"].startswith("done:invalid_args")


async def test_approval_pause_resume_and_rejection(mm):
    sent = []

    @mm.tool(side_effect=True)
    def wire(amount: float) -> str:
        sent.append(amount)
        return "sent"

    await mm.add_policy(PolicyRuleIn(name="approve-wires", effect=PolicyEffect.REQUIRE_APPROVAL, tools=["wire"]))
    make_agent(mm, "payer", ["wire"], tool_then_answer("wire", {"amount": 10.0}))
    run = await mm.run("payer", "pay")
    assert run.status == "waiting_approval" and sent == []
    [appr] = await mm.repos.approvals.list(status="pending")
    _, resumed = await mm.resolve_approval(appr.id, True, resolver="alice")
    assert resumed.status == "succeeded" and sent == [10.0]

    await mm.run("payer", "pay again")
    [appr2] = await mm.repos.approvals.list(status="pending")
    _, resumed2 = await mm.resolve_approval(appr2.id, False, resolver="bob", note="not today")
    assert sent == [10.0]
    assert resumed2.status == "succeeded" and resumed2.result["answer"].startswith("done:blocked")


async def test_cancel_running_and_waiting_runs(mm):
    started = asyncio.Event()

    @mm.tool(timeout_s=5)
    async def wait_forever() -> str:
        started.set()
        await asyncio.sleep(0.3)
        return "x"

    make_agent(mm, "w", ["wait_forever"], lambda req: {"type": "tool_call", "tool": "wait_forever", "args": {}},
               limits=Limits(repeated_failure_limit=99, max_steps=50))
    run = await mm.run("w", "t", wait=False)
    await started.wait()
    cancelled = await mm.cancel(run.id)
    assert cancelled.status == "cancelled"

    await mm.add_policy(PolicyRuleIn(name="gate", effect=PolicyEffect.REQUIRE_APPROVAL, tools=["wait_forever"]))
    run2 = await mm.run("w", "t")
    assert run2.status == "waiting_approval"
    assert (await mm.cancel(run2.id)).status == "cancelled"
    assert (await mm.repos.approvals.list(run_id=run2.id))[0].status == "rejected"


async def test_crash_recovery_resumes_from_checkpoint(mm):
    @mm.tool()
    def step(i: int) -> int:
        return i

    def counter(req):
        if len(req.history) < 3:
            return {"type": "tool_call", "tool": "step", "args": {"i": len(req.history)}}
        return {"type": "final_answer", "answer": str([h["outcome"]["result"] for h in req.history])}

    make_agent(mm, "c", ["step"], counter)
    run = await mm.run("c", "t")
    # Simulate a crash after step 2: roll the run back to its step-2 checkpoint and RUNNING state.
    ckpts = await mm.repos.runs.list_checkpoints(run.id)
    from sqlalchemy import delete

    from mindmesh.storage.orm import CheckpointRow
    async with mm.db.session() as s:
        await s.execute(delete(CheckpointRow).where(CheckpointRow.id.in_([c["id"] for c in ckpts[2:]])))
    await mm.repos.runs.update(run.id, status="running", result=None, ended_at=None)
    recovered = await mm.resume(run.id)
    assert recovered.status == "succeeded" and recovered.result["answer"] == "[0, 1, 2]"
    assert await mm.repos.events.list(run.id, types=["run.resumed"])


def test_parse_action_variants():
    a = parse_action('<think>hmm</think>```json\n{"type":"tool_call","tool":"x","args":{"a":1}}\n```')
    assert a.tool == "x"
    b = parse_action('Sure! {"answer": "42"} hope that helps')
    assert b.type == "final_answer" and b.answer == "42"
    with pytest.raises(ModelOutputError):
        parse_action('{"type": "dance"}')


async def test_secrets_never_reach_the_event_log(mm):
    @mm.tool()
    def login(user: str, password: str) -> dict:
        return {"token": "abc123secret", "note": "key sk-THISISASECRETKEY12345"}

    make_agent(mm, "auth", ["login"], tool_then_answer("login", {"user": "u", "password": "p@ss"}))
    run = await mm.run("auth", "log in")
    blob = json.dumps([e.payload for e in await mm.repos.events.list(run.id)])
    assert "p@ss" not in blob and "abc123secret" not in blob and "THISISASECRETKEY" not in blob


async def test_remember_outcomes_writes_episode(mm):
    make_agent(mm, "mem", [], lambda req: {"type": "final_answer", "answer": "ok"}, remember_outcomes=True)
    run = await mm.run("mem", "summarise the weekly report")
    eps = await mm.memory.list(kind="episode")
    assert eps and eps[0].run_id == run.id and eps[0].scope == "agent:mem"
