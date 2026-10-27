"""The guided experiment API and the explain-before-you-change endpoints behind it."""

import pytest

from mindmesh.demo import experiment, refund

from ..conftest import wait_for_status

V = "/api/v1"
DONE = {"succeeded", "failed", "cancelled"}


@pytest.fixture(autouse=True)
def _unpaced(monkeypatch):
    monkeypatch.setattr(experiment, "DEMO_MODEL", "scripted:refund-support?think_ms=0")


async def run_scenario(api, scenario, protected=True):
    r = await api.post(f"{V}/experiments/refund/runs", json={"scenario": scenario, "protected": protected})
    assert r.status_code == 201, r.text
    return await wait_for_status(api, r.json()["id"], DONE)


async def events(api, run_id, *types):
    return (await api.get(f"{V}/runs/{run_id}/events", params={"type": list(types)})).json()


async def test_first_run_reset_seeds_the_failing_scenario_and_keeps_other_data(api):
    me = (await api.get(f"{V}/me")).json()
    assert me["model_mode"] == "demo" and me["live_model"] is None
    assert (await api.get(f"{V}/experiments/refund")).json()["seeded"] is False

    keep = (await api.post(f"{V}/memories", json={"content": "Our SLA is 99.9% uptime.", "subject_key": "sla"})).json()
    await api.post(f"{V}/policies", json={"name": "my-rule", "effect": "deny", "tools": ["shell.*"]})
    for _ in range(2):  # resetting twice leaves exactly one copy of the scenario
        state = (await api.post(f"{V}/experiments/refund/reset")).json()
    assert state["seeded"] and not state["fixed"]
    assert state["memories"]["current_policy"]["scope"] == "agent:billing"
    assert [r["name"] for r in state["rules"]] == [
        "block-large-refunds", "one-refund-per-run", "approve-refunds-over-100", "allow-support-tools"]
    assert len((await api.get(f"{V}/memories", params={"subject_key": "refund_policy"})).json()) == 2
    assert (await api.get(f"{V}/memories/{keep['id']}")).json()["status"] == "active"
    assert "my-rule" in {p["name"] for p in (await api.get(f"{V}/policies")).json()}

    run = await run_scenario(api, "original")
    assert run["label"] == "experiment:original"
    assert run["config"]["agent_spec"]["model"].startswith("scripted:refund-support")
    assert run["result"]["answer"].startswith("DENIED")
    state = (await api.get(f"{V}/experiments/refund")).json()
    assert state["runs"]["original"]["id"] == run["id"] and state["runs"]["rerun"] is None


async def test_live_mode_requires_a_configured_model(api):
    await api.post(f"{V}/experiments/refund/reset")
    r = await api.post(f"{V}/experiments/refund/runs", json={"scenario": "original", "mode": "live"})
    assert r.status_code == 400 and "MINDMESH_MODEL" in r.json()["detail"]


async def test_memory_impact_explains_the_fix_without_writing(api):
    state = (await api.post(f"{V}/experiments/refund/reset")).json()
    original = await run_scenario(api, "original")
    current = state["memories"]["current_policy"]
    retrievals = len((await api.get(f"{V}/memories/{current['id']}/retrievals")).json())

    r = await api.post(f"{V}/memories/{current['id']}/impact", json={"change": {"scope": "project"}})
    assert r.status_code == 200, r.text
    impact = r.json()
    assert impact["changes"] == {"scope": {"before": "agent:billing", "after": "project"}}
    assert impact["new_version"] == 2
    assert {m["content"] for m in impact["supersedes"]} == {refund.NEW_POLICY, refund.OLD_POLICY}
    support = next(a for a in impact["visibility"] if a["agent"] == "support")
    assert support["before"] is False and support["after"] is True
    [run] = impact["runs"]
    assert run["run_id"] == original["id"] and run["answer"].startswith("DENIED")
    assert [i["content"] for i in run["newly_included"]] == [refund.NEW_POLICY]
    [dropped] = run["newly_excluded"]
    assert dropped["content"] == refund.OLD_POLICY and dropped["reason"] == "superseded"

    # a dry run: the memory is untouched and no retrievals were recorded
    assert len((await api.get(f"{V}/memories/{current['id']}/versions")).json()) == 1
    assert len((await api.get(f"{V}/memories/{current['id']}/retrievals")).json()) == retrievals

    await api.patch(f"{V}/memories/{current['id']}", json={"scope": "project"})
    assert (await api.get(f"{V}/experiments/refund")).json()["fixed"] is True
    rerun = (await api.post(f"{V}/runs/{original['id']}/rerun", json={})).json()
    done = await wait_for_status(api, rerun["id"], DONE)
    assert done["result"]["answer"].startswith("APPROVED")
    assert (await api.get(f"{V}/experiments/refund")).json()["runs"]["rerun"]["id"] == rerun["id"]


async def test_impact_rejects_editing_an_inactive_memory(api):
    state = (await api.post(f"{V}/experiments/refund/reset")).json()
    mid = state["memories"]["current_policy"]["id"]
    await api.patch(f"{V}/memories/{mid}", json={"scope": "project"})
    r = await api.post(f"{V}/memories/{mid}/impact", json={"change": {"scope": "project"}})
    assert r.status_code == 400 and "superseded" in r.json()["detail"]


async def test_prompt_injection_blocked_only_by_policy(api):
    await api.post(f"{V}/experiments/refund/reset")
    protected = await run_scenario(api, "injection")
    assert protected["result"]["answer"].startswith("APPROVED: refunded $35.00")
    [deny] = [e for e in await events(api, protected["id"], "policy.decision") if e["payload"]["effect"] == "deny"]
    assert deny["payload"]["rule_name"] == "block-large-refunds" and deny["payload"]["args"]["amount"] == 4999

    exposed = await run_scenario(api, "injection", protected=False)
    assert exposed["label"] == "experiment:injection:unprotected"
    paid = [e["payload"]["result"]["amount"] for e in await events(api, exposed["id"], "tool.finished")
            if e["payload"]["tool"] == "refund.issue"]
    assert 4999 in paid  # the model obeyed the injection; nothing outside it said no (simulated ledger)

    runs = (await api.get(f"{V}/experiments/refund")).json()["runs"]
    assert runs["injection"]["facts"]["refunds"] == [
        {"amount": 4999.0, "status": "blocked", "rule": "block-large-refunds"},
        {"amount": 35.0, "status": "ok", "rule": "allow-support-tools"}]
    assert {"amount": 4999.0, "status": "ok", "rule": None} in runs["injection:unprotected"]["facts"]["refunds"]


async def test_policy_impact_shows_which_recorded_decisions_would_flip(api):
    await api.post(f"{V}/experiments/refund/reset")
    run = await run_scenario(api, "injection")
    impact = (await api.post(f"{V}/policies/impact", json={"disable": ["block-large-refunds"]})).json()
    assert impact["rules"] == [{"rule": "block-large-refunds", "change": "modified", "fields": ["enabled"],
                                "before": {"enabled": True}, "after": {"enabled": False}}]
    [flip] = impact["changes"]
    assert flip["run_id"] == run["id"] and flip["args"]["amount"] == 4999
    assert flip["before"]["rule_name"] == "block-large-refunds" and flip["before"]["effect"] == "deny"
    assert flip["after"]["effect"] == "require_approval"  # the next matching rule
    assert impact["changed"] == 1 and impact["evaluated"] == impact["unchanged"] + 1
    assert (await api.get(f"{V}/policies")).json()[0]["enabled"] is True  # nothing written

    yaml = (await api.get(f"{V}/policies/yaml")).json()["yaml"]
    same = (await api.post(f"{V}/policies/impact", json={"yaml": yaml})).json()
    assert same["rules"] == [] and same["changed"] == 0
    bad = await api.post(f"{V}/policies/impact", json={"disable": ["nope"]})
    assert bad.status_code == 400


async def test_failure_injection_recovers_only_with_retries(api):
    await api.post(f"{V}/experiments/refund/reset")
    mid = (await api.get(f"{V}/experiments/refund")).json()["memories"]["current_policy"]["id"]
    await api.patch(f"{V}/memories/{mid}", json={"scope": "project"})

    ok = await run_scenario(api, "faults")
    assert ok["result"]["answer"].startswith("APPROVED")
    retries = await events(api, ok["id"], "tool.retry")
    assert [e["payload"]["injected"] for e in retries] == [True, True]
    assert "injected fault 1/2" in retries[0]["payload"]["error"]

    fragile = await run_scenario(api, "faults", protected=False)
    assert fragile["result"]["answer"].startswith("ESCALATED")
    [failed] = await events(api, fragile["id"], "tool.failed")
    assert failed["payload"]["injected"] is True
    runs = (await api.get(f"{V}/experiments/refund")).json()["runs"]
    assert runs["faults"]["facts"]["retries"] == 2 and runs["faults:unprotected"]["facts"]["injected_faults"] == 1

    # reruns inherit the fault plan (it is part of the recorded run configuration)
    rerun = (await api.post(f"{V}/runs/{ok['id']}/rerun", json={})).json()
    done = await wait_for_status(api, rerun["id"], DONE)
    assert done["config"]["overrides"]["faults"] == {"crm.lookup": 2}
    assert len(await events(api, rerun["id"], "tool.retry")) == 2
