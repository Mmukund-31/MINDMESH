import pytest

from mindmesh.core.types import MemoryUpdate, RunOverrides
from mindmesh.demo import refund, research
from mindmesh.eval.runner import aggregate, merge_overrides, run_suite
from mindmesh.eval.suite import load_suite


async def test_signature_scenario_fail_fix_rerun(refund_mm):
    mm = refund_mm
    task, inp = refund.task_for("C-1042", "A-7731")
    r1 = await mm.run("support", task, inp)
    assert r1.result["answer"].startswith("DENIED")
    receipt = (await mm.repos.events.list(r1.id, types=["context.assembled"]))[-1].payload
    excluded = {(i["item_id"], i["reason"]) for i in receipt["excluded"]}
    assert (mm.test_ids["new_policy"], "scope_mismatch") in excluded

    await mm.memory.update(mm.test_ids["new_policy"], MemoryUpdate(scope="project"))
    r2 = await mm.rerun(r1.id)
    assert r2.kind == "rerun" and r2.parent_run_id == r1.id
    assert r2.result["answer"].startswith("APPROVED")
    assert mm.test_world.ledger[-1]["amount"] == 79.0

    cmp = await mm.compare(r1.id, r2.id)
    assert cmp["divergence_step"] == 1 and not cmp["identical"]
    added = {m for s in cmp["steps"] for m in s["context_added"]}
    assert any(cmp["memories"][m]["subject_key"] == "refund_policy" for m in added)


async def test_safe_replay_never_executes_tools(refund_mm):
    mm = refund_mm
    await mm.memory.update(mm.test_ids["new_policy"], MemoryUpdate(scope="project"))
    task, inp = refund.task_for("C-1042", "A-7731")
    original = await mm.run("support", task, inp)
    assert len(mm.test_world.ledger) == 1
    replay = await mm.replay(original.id)
    assert replay.kind == "replay" and replay.result == original.result
    assert len(mm.test_world.ledger) == 1  # the side-effecting refund was NOT issued again
    started = await mm.repos.events.list(replay.id, types=["tool.started"])
    assert started and all(e.payload.get("replayed") for e in started)
    assert (await mm.compare(original.id, replay.id))["identical"]


async def test_replay_requires_terminal_run(refund_mm):
    mm = refund_mm
    task, inp = refund.task_for("C-2077", "A-9020")  # $120 -> waits for approval
    run = await mm.run("support", task, inp)
    assert run.status == "waiting_approval"
    with pytest.raises(ValueError):
        await mm.replay(run.id)


async def test_rerun_with_overrides(refund_mm):
    mm = refund_mm
    task, inp = refund.task_for("C-1042", "A-7731")
    r1 = await mm.run("support", task, inp)
    r2 = await mm.rerun(r1.id, RunOverrides(memory_scopes=["project", "agent:*"]))
    # with billing scope visible, the higher-trust updated policy wins the conflict
    assert r2.result["answer"].startswith("APPROVED")
    assert r2.config["agent_spec"]["memory_scopes"] == ["project", "agent:*"]


async def test_prompt_injection_is_blocked_by_policy(refund_mm):
    mm = refund_mm
    task, inp = refund.task_for("C-2077", "A-6666")
    run = await mm.run("support", task, inp)
    assert all(e["amount"] < 500 for e in mm.test_world.ledger)
    denied = [e for e in await mm.repos.events.list(run.id, types=["policy.decision"]) if e.payload["effect"] == "deny"]
    assert denied and denied[0].payload["rule_name"] == "block-large-refunds"


async def test_research_workflow_with_retry_and_verifier(mm):
    research.install(mm)
    research.reset_faults()
    wid = await mm.run_workflow(research.TEMPLATE)
    wf = await mm.repos.workflows.get_run(wid)
    tasks = {t.key: t for t in await mm.repos.workflows.tasks(wid)}
    assert wf.status == "succeeded"
    assert tasks["write"].attempts == 2 and tasks["verify"].output["answer"].startswith("APPROVE")
    types = [e.type for e in await mm.repos.events.list(wid)]
    assert "verifier.rejected" in types and "handoff" in types
    runs = await mm.repos.runs.list(workflow_run_id=wid)
    assert len(runs) == 7  # plan, 2 research, write x2, verify x2
    retries = [e for r in runs for e in await mm.repos.events.list(r.id, types=["tool.retry"])]
    assert len(retries) == 1  # flaky search recovered
    assert len(await mm.repos.workflows.evidence(wid)) >= 4


async def test_workflow_validation(mm):
    research.install(mm)
    bad = research.TEMPLATE.model_copy(deep=True)
    bad.tasks[0].depends_on = ["verify"]
    with pytest.raises(ValueError, match="cycle"):
        await mm.run_workflow(bad)


async def test_workflow_failure_skips_dependents(mm):
    from mindmesh import AgentSpec, WorkflowSpec, WorkflowTaskSpec
    from mindmesh.models.scripted import ScriptedProvider

    mm.register_provider_instance("scripted:dies", ScriptedProvider("dies", lambda req: "garbage"))
    mm.register_provider_instance("scripted:fine", ScriptedProvider("fine", lambda req: {"type": "final_answer", "answer": "ok"}))
    mm.agent(AgentSpec(name="dies", model="scripted:dies"))
    mm.agent(AgentSpec(name="fine", model="scripted:fine"))
    spec = WorkflowSpec(name="w", goal="g", tasks=[
        WorkflowTaskSpec(key="a", agent="dies", task="x", max_attempts=2),
        WorkflowTaskSpec(key="b", agent="fine", task="y", depends_on=["a"]),
        WorkflowTaskSpec(key="c", agent="fine", task="z"),
    ])
    wid = await mm.run_workflow(spec)
    tasks = {t.key: t for t in await mm.repos.workflows.tasks(wid)}
    assert tasks["a"].status == "failed" and tasks["a"].attempts == 2
    assert tasks["b"].status == "skipped" and tasks["c"].status == "succeeded"
    assert (await mm.repos.workflows.get_run(wid)).status == "failed"


def test_merge_overrides_deep_merges_dicts():
    m = merge_overrides(RunOverrides(context={"strategy": "naive"}, enforce_policies=False),
                        RunOverrides(context={"budget_tokens": 100}))
    assert m.context == {"strategy": "naive", "budget_tokens": 100} and m.enforce_policies is False


async def test_benchmark_is_reproducible_and_mindmesh_wins(mm):
    suite = load_suite("refund")
    rep1 = await run_suite(suite, store=mm)
    rep2 = await run_suite(suite)
    m = {k: v["metrics"] for k, v in rep1["variants"].items()}
    assert m["mindmesh"]["success_rate"] == 1.0
    assert m["mindmesh"]["success_rate"] > m["mindmesh-misconfigured"]["success_rate"] > 0
    assert m["mindmesh"]["success_rate"] > m["baseline"]["success_rate"]
    assert m["baseline"]["unsafe_actions_executed"] >= 1 and m["mindmesh"]["unsafe_actions_executed"] == 0
    assert m["mindmesh"]["evidence_recall"] == 1.0
    for v in rep1["variants"]:
        assert [r["success"] for r in rep1["variants"][v]["results"]] == [r["success"] for r in rep2["variants"][v]["results"]]
    assert len(await mm.repos.evals.list()) == 3


def test_aggregate_empty_safe():
    assert aggregate([])["success_rate"] == 0.0
