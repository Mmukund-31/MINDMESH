import asyncio

from mindmesh.demo import refund

from ..conftest import wait_for_status

V = "/api/v1"


async def seed(api):
    await refund.seed(api.app.state.mm, memory_state="broken")


async def start(api, cid, oid):
    task, inp = refund.task_for(cid, oid)
    r = await api.post(f"{V}/runs", json={"agent": "support", "task": task, "input": inp})
    assert r.status_code == 201, r.text
    return r.json()


async def test_health_and_me(api):
    assert (await api.get("/healthz")).json()["status"] == "ok"
    me = (await api.get(f"{V}/me")).json()
    assert me["project_name"] == "alpha"
    agents = {a["name"] for a in (await api.get(f"{V}/agents")).json()}
    assert {"support", "planner", "researcher", "writer", "verifier"} <= agents
    tools = {t["name"]: t for t in (await api.get(f"{V}/tools")).json()}
    assert tools["refund.issue"]["side_effect"] is True


async def test_run_lifecycle_trace_and_receipts(api):
    await seed(api)
    run = await start(api, "C-1042", "A-7731")
    done = await wait_for_status(api, run["id"], {"succeeded", "failed"})
    assert done["result"]["answer"].startswith("DENIED")
    trace = (await api.get(f"{V}/runs/{run['id']}/trace")).json()
    assert [s["step"] for s in trace["steps"]] == [1, 2, 3]  # crm.lookup, orders.get, final
    kinds = {n["kind"] for s in trace["steps"] for n in s["nodes"]}
    assert {"context", "model", "policy", "tool"} <= kinds
    receipts = (await api.get(f"{V}/runs/{run['id']}/receipts")).json()
    assert any(i["reason"] == "scope_mismatch" for i in receipts[0]["excluded"])
    events = (await api.get(f"{V}/runs/{run['id']}/events", params={"after": 3})).json()
    assert events[0]["seq"] == 4
    fb = await api.post(f"{V}/runs/{run['id']}/feedback", json={"verdict": "incorrect", "note": "premium"})
    assert fb.json()["feedback"]["verdict"] == "incorrect"
    ov = (await api.get(f"{V}/stats/overview")).json()
    assert ov["runs"]["total"] == 1 and ov["recent_failures"][0]["id"] == run["id"]


async def test_memory_explorer_fix_then_rerun_and_compare(api):
    await seed(api)
    run = await start(api, "C-1042", "A-7731")
    await wait_for_status(api, run["id"], {"succeeded"})
    mems = (await api.get(f"{V}/memories", params={"subject_key": "refund_policy"})).json()
    billing = next(m for m in mems if m["scope"] == "agent:billing")
    conflicts = (await api.get(f"{V}/memories/conflicts")).json()
    assert conflicts and conflicts[0]["subject_key"] == "refund_policy"
    hist = (await api.get(f"{V}/memories/{billing['id']}/retrievals")).json()
    assert hist and hist[0]["included"] is False and hist[0]["reason"] == "scope_mismatch"

    patched = await api.patch(f"{V}/memories/{billing['id']}", json={"scope": "project", "reason": "global policy"})
    assert patched.status_code == 200 and patched.json()["version"] == 2
    versions = (await api.get(f"{V}/memories/{patched.json()['id']}/versions")).json()
    assert [v["status"] for v in versions] == ["superseded", "active"]

    preview = (await api.post(f"{V}/context/preview", json={"query": "refund policy premium", "agent": "support"})).json()
    assert any("30 days" in i["content"] for i in preview["included"])

    rerun = (await api.post(f"{V}/runs/{run['id']}/rerun", json={})).json()
    done = await wait_for_status(api, rerun["id"], {"succeeded", "failed"})
    assert done["result"]["answer"].startswith("APPROVED")
    cmp = (await api.get(f"{V}/compare", params={"a": run["id"], "b": rerun["id"]})).json()
    assert cmp["divergence_step"] == 1
    replay = (await api.post(f"{V}/runs/{run['id']}/replay")).json()
    rdone = await wait_for_status(api, replay["id"], {"succeeded", "failed"})
    assert rdone["result"] == (await api.get(f"{V}/runs/{run['id']}")).json()["result"]


async def test_memory_crud_search_retract(api):
    r = await api.post(f"{V}/memories", json={"content": "Our SLA is 99.9% monthly uptime.", "subject_key": "sla",
                                              "tags": ["ops"], "provenance": {"source_type": "manual", "source_ref": "contract.pdf"}})
    assert r.status_code == 201
    mid = r.json()["id"]
    hits = (await api.get(f"{V}/memories/search", params={"q": "uptime SLA"})).json()
    assert hits[0]["memory"]["id"] == mid
    rt = await api.post(f"{V}/memories/{mid}/retract", json={"reason": "contract renegotiated"})
    assert rt.json()["status"] == "retracted"
    assert (await api.get(f"{V}/memories", params={"status": "active", "q": "SLA"})).json() == []
    bad = await api.post(f"{V}/memories", json={"content": "x", "scope": "root; DROP TABLE"})
    assert bad.status_code == 422


async def test_approval_flow_via_control_room(api):
    await seed(api)
    run = await start(api, "C-2077", "A-9020")  # $120 -> approval
    await wait_for_status(api, run["id"], {"waiting_approval"})
    pending = (await api.get(f"{V}/approvals", params={"status": "pending"})).json()
    assert len(pending) == 1 and pending[0]["args"]["amount"] == 120.0
    blocked = (await api.get(f"{V}/blocked-actions")).json()
    assert any(b["effect"] == "require_approval" for b in blocked)
    r = await api.post(f"{V}/approvals/{pending[0]['id']}/resolve", json={"approve": True, "resolver": "lead"})
    assert r.json()["status"] == "approved"
    done = await wait_for_status(api, run["id"], {"succeeded", "failed"})
    assert done["result"]["answer"].startswith("APPROVED")
    again = await api.post(f"{V}/approvals/{pending[0]['id']}/resolve", json={"approve": False})
    assert again.status_code == 409  # already resolved: state machine forbids it


async def test_policies_yaml_and_simulation(api):
    await seed(api)
    y = (await api.get(f"{V}/policies/yaml")).json()["yaml"]
    assert "block-large-refunds" in y
    sim = await api.post(f"{V}/policies/simulate", json={"tool": "refund.issue", "agent": "support",
                                                          "args": {"order_id": "A-1", "amount": 9000.0, "reason": "x"}})
    assert sim.json()["effect"] == "deny"
    sim2 = await api.post(f"{V}/policies/simulate", json={"tool": "refund.issue", "agent": "support",
                                                           "args": {"order_id": "A-1", "amount": "lots", "reason": "x"}})
    assert sim2.status_code == 422
    new = y.replace("value: 100", "value: 200")
    rules = (await api.put(f"{V}/policies/yaml", json={"yaml": new})).json()
    assert len(rules) == 4
    bad = await api.put(f"{V}/policies/yaml", json={"yaml": "rules: [{name: x, effect: explode}]"})
    assert bad.status_code == 422
    p = (await api.post(f"{V}/policies", json={"name": "no-crm", "effect": "deny", "tools": ["crm.*"], "priority": 1})).json()
    assert (await api.delete(f"{V}/policies/{p['id']}")).status_code == 204


async def test_sse_stream_delivers_events_and_ends(api):
    await seed(api)
    run = await start(api, "C-3310", "A-9555")
    await wait_for_status(api, run["id"], {"succeeded"})
    body = ""
    async with api.stream("GET", f"{V}/runs/{run['id']}/stream") as resp:
        assert resp.headers["content-type"].startswith("text/event-stream")
        async for chunk in resp.aiter_text():
            body += chunk
            if "event: end" in body:
                break
    assert "event: event" in body and '"type":"run.created"' in body and "event: run" in body


async def test_cancel_endpoint(api):
    await seed(api)
    run = await start(api, "C-2077", "A-9020")
    await wait_for_status(api, run["id"], {"waiting_approval"})
    c = (await api.post(f"{V}/runs/{run['id']}/cancel")).json()
    assert c["status"] == "cancelled"
    assert (await api.post(f"{V}/runs/{run['id']}/resume")).status_code == 400


async def test_workflow_endpoints(api):
    tpl = (await api.get(f"{V}/workflows/templates")).json()
    assert tpl[0]["name"] == "research-brief"
    wf = (await api.post(f"{V}/workflows", json={"template": "research-brief"})).json()
    for _ in range(200):
        detail = (await api.get(f"{V}/workflows/{wf['id']}")).json()
        if detail["status"] != "running":
            break
        await asyncio.sleep(0.05)
    assert detail["status"] == "succeeded"
    assert {t["key"] for t in detail["tasks"]} == {"plan", "research_hnsw", "research_ivf", "write", "verify"}
    assert detail["evidence"] and any(e["type"] == "handoff" for e in detail["events"])
    assert (await api.get(f"{V}/workflows")).json()[0]["succeeded"] == 5


async def test_eval_endpoints(api):
    suites = (await api.get(f"{V}/evals/suites")).json()
    assert suites[0]["name"] == "refund"
    job = (await api.post(f"{V}/evals", json={"suite": "refund", "variants": ["mindmesh"]})).json()
    for _ in range(400):
        j = (await api.get(f"{V}/evals/jobs/{job['id']}")).json()
        if j["status"] != "running":
            break
        await asyncio.sleep(0.05)
    assert j["status"] == "succeeded", j
    ev = (await api.get(f"{V}/evals/{j['eval_ids'][0]}")).json()
    assert ev["metrics"]["success_rate"] == 1.0 and len(ev["results"]) == 7
