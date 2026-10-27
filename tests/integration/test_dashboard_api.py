"""API behind the Studio dashboard: audit trail, overview model usage and policy interventions, evaluation report."""

from mindmesh.demo import refund

from ..conftest import OTHER_KEY, wait_for_status

V = "/api/v1"


async def _refund_runs(api):
    mm = api.app.state.mm
    await refund.seed(mm, memory_state="broken")
    ids = []
    for cid, oid in (("C-1042", "A-7731"), ("C-2077", "A-9020")):
        task, inp = refund.task_for(cid, oid)
        run = (await api.post(f"{V}/runs", json={"agent": "support", "task": task, "input": inp})).json()
        ids.append(run["id"])
    await wait_for_status(api, ids[0], {"succeeded"})
    await wait_for_status(api, ids[1], {"waiting_approval"})
    return ids


async def test_audit_trail_records_changes_with_the_acting_key(api):
    _, paused = await _refund_runs(api)
    rule = next(r for r in (await api.get(f"{V}/policies")).json() if r["name"] == "block-large-refunds")
    body = {k: rule[k] for k in ("name", "description", "effect", "tools", "roles", "agents", "conditions", "priority",
                                 "max_calls_per_run")}
    assert (await api.put(f"{V}/policies/{rule['id']}", json={**body, "enabled": False})).status_code == 200
    mem = next(m for m in (await api.get(f"{V}/memories")).json() if m["scope"] == "agent:billing")
    await api.patch(f"{V}/memories/{mem['id']}", json={"scope": "project", "reason": "applies to all agents"})
    [appr] = (await api.get(f"{V}/approvals", params={"status": "pending"})).json()
    await api.post(f"{V}/approvals/{appr['id']}/resolve", json={"approve": False, "resolver": "cfo", "note": "no"})
    key = (await api.post(f"{V}/keys", json={"name": "ci", "role": "read"})).json()

    trail = (await api.get(f"{V}/audit")).json()
    actions = [e["action"] for e in trail]
    assert actions[:4] == ["key.created", "approval.rejected", "memory.updated", "policy.updated"]  # newest first
    by_action = {e["action"]: e for e in trail}
    assert by_action["policy.updated"]["summary"] == "rule 'block-large-refunds' disabled"
    assert by_action["policy.updated"]["details"]["changes"]["enabled"] == {"before": True, "after": False}
    mu = by_action["memory.updated"]
    assert "v1 -> v2: scope (applies to all agents)" in mu["summary"]
    assert mu["details"]["changes"]["scope"] == {"before": "agent:billing", "after": "project"}
    assert by_action["approval.rejected"]["details"]["run_id"] == paused
    assert all(e["actor"] == "key:bootstrap" for e in trail)

    assert [e["action"] for e in (await api.get(f"{V}/audit", params={"target_type": "memory"})).json()] == ["memory.updated"]
    # project isolation, and read-only keys can see the trail but not change anything
    assert (await api.get(f"{V}/audit", headers={"X-API-Key": OTHER_KEY})).json() == []
    ro = {"X-API-Key": key["key"]}
    assert (await api.get(f"{V}/audit", headers=ro)).status_code == 200
    assert (await api.put(f"{V}/policies/{rule['id']}", json=body, headers=ro)).status_code == 403


async def test_policy_yaml_replacement_is_summarised(api):
    await refund.seed(api.app.state.mm, memory_state="broken")
    yaml = (await api.get(f"{V}/policies/yaml")).json()["yaml"]
    new = yaml.replace("value: 500", "value: 400") + (
        "- name: deny-deletes\n  effect: deny\n  tools: ['*.delete']\n  priority: 5\n")
    assert (await api.put(f"{V}/policies/yaml", json={"yaml": new})).status_code == 200
    [e] = (await api.get(f"{V}/audit")).json()
    assert e["action"] == "policy.replaced"
    assert e["details"]["added"] == ["deny-deletes"] and e["details"]["changed"] == ["block-large-refunds"]
    assert e["summary"] == "saved policy YAML: 1 added, 1 changed"


async def test_overview_reports_model_usage_and_policy_interventions(api):
    await _refund_runs(api)
    d = (await api.get(f"{V}/stats/overview")).json()
    [m] = d["models"]
    assert m["model"] == "scripted:refund-support" and m["calls"] >= 4 and m["tokens_in"] > 0 and m["errors"] == 0
    assert m["latency_p50_ms"] is not None
    paused = [i for i in d["policy"]["interventions"] if i["effect"] == "require_approval"]
    assert paused == [{"rule": "approve-refunds-over-100", "effect": "require_approval", "count": 1,
                       "tools": {"refund.issue": 1}}]


async def test_evaluation_report_is_markdown(api):
    from mindmesh.eval.runner import run_suite
    from mindmesh.eval.suite import load_suite

    assert (await api.get(f"{V}/export/evals/report", params={"suite": "refund"})).status_code == 404
    await run_suite(load_suite("refund"), variants=["baseline", "mindmesh"], store=api.app.state.mm, results_dir=None)
    r = await api.get(f"{V}/export/evals/report", params={"suite": "refund"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/markdown")
    assert 'filename="refund-report.md"' in r.headers["content-disposition"]
    text = r.text
    assert text.startswith("# Benchmark: `refund`")
    assert "| Task success rate |" in text and "## Per-task outcomes" in text
    assert text.index("`baseline`") < text.index("`mindmesh`")  # suite order, not arbitrary
