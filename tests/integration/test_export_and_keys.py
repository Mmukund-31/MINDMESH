"""JSON export/import of runs and benchmark results, and API-key management."""

import json

from mindmesh import MindMesh
from mindmesh.demo import refund
from mindmesh.export import RUN_FORMAT, export_evals, export_run, import_run

from ..conftest import API_KEY, OTHER_KEY, wait_for_status

V = "/api/v1"


async def _failed_refund_run(mm):
    await refund.seed(mm, memory_state="broken")
    task, inp = refund.task_for("C-1042", "A-7731")
    return await mm.run("support", task, inp)


async def test_run_export_is_self_contained_json(refund_mm):
    run = await _failed_refund_run(refund_mm)
    doc = json.loads(json.dumps(await export_run(refund_mm, run.id)))  # round-trips through plain JSON
    assert doc["format"] == RUN_FORMAT and doc["run"]["id"] == run.id
    s = doc["summary"]
    assert s["status"] == "succeeded" and s["answer"].startswith("DENIED")  # the reproducible wrong decision
    assert [t["tool"] for t in s["timeline"] if t["tool"]] and s["model"] == "scripted:refund-support"
    assert {e["type"] for e in doc["events"]} >= {"run.created", "context.assembled", "model.called",
                                                 "step.finished"}
    assert doc["run"]["config"]["agent_spec"]["name"] == "support"


async def test_imported_run_replays_in_another_database_without_the_agent(refund_mm, tmp_path):
    original = await _failed_refund_run(refund_mm)
    doc = await export_run(refund_mm, original.id)

    other = await MindMesh(f"sqlite:///{tmp_path / 'teammate.db'}", project="triage").init()
    try:
        assert "support" not in other.agents  # the teammate has no copy of the agent or its tools
        copy = await import_run(other, json.loads(json.dumps(doc)))
        assert copy.id != original.id and copy.label == f"imported from {original.id}"
        assert len(await other.repos.events.list(copy.id)) == len(doc["events"])
        replay = await other.replay(copy.id)
        assert replay.status == "succeeded" and replay.result["answer"] == original.result["answer"]
        assert not await other.repos.events.list(replay.id, types=["replay.diverged"])
        cmp = await other.compare(copy.id, replay.id)  # every step: same action and the same recorded outcome
        assert all(s["same_action"] for s in cmp["steps"])  # (context may differ: the teammate has no memories)
        assert [s["a"]["outcome"]["status"] for s in cmp["steps"]] == [s["b"]["outcome"]["status"] for s in cmp["steps"]]
        assert "blocked" not in [s["b"]["outcome"]["status"] for s in cmp["steps"]]
    finally:
        await other.close()


async def test_import_rejects_wrong_format_and_unfinished_runs(refund_mm):
    run = await _failed_refund_run(refund_mm)
    doc = await export_run(refund_mm, run.id)
    for bad, msg in (({**doc, "format": "x"}, "not a"), ({**doc, "run": {**doc["run"], "status": "running"}},
                                                           "only finished")):
        try:
            await import_run(refund_mm, bad)
        except ValueError as e:
            assert msg in str(e)
        else:
            raise AssertionError("import accepted an invalid document")


async def test_eval_export(refund_mm):
    from mindmesh.eval.runner import run_suite
    from mindmesh.eval.suite import load_suite

    await run_suite(load_suite("refund"), variants=["baseline"], store=refund_mm, results_dir=None)
    doc = await export_evals(refund_mm, suite="refund")
    [ev] = doc["evals"]
    assert doc["format"] == "mindmesh.eval/v1" and ev["variant"] == "baseline"
    assert ev["metrics"] and ev["results"] and json.dumps(doc)


async def test_export_and_import_endpoints(api):
    mm = api.app.state.mm
    await refund.seed(mm, memory_state="broken")
    task, inp = refund.task_for("C-1042", "A-7731")
    run = (await api.post(f"{V}/runs", json={"agent": "support", "task": task, "input": inp})).json()
    await wait_for_status(api, run["id"], {"succeeded"})

    r = await api.get(f"{V}/runs/{run['id']}/export")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    doc = r.json()
    assert doc["format"] == RUN_FORMAT
    bulk = (await api.get(f"{V}/export/runs", params={"status": "succeeded"})).json()
    assert [b["run"]["id"] for b in bulk["runs"]] == [run["id"]]
    assert (await api.get(f"{V}/runs/{run['id']}/export", headers={"X-API-Key": OTHER_KEY})).status_code == 404

    imported = await api.post(f"{V}/runs/import", json=doc, headers={"X-API-Key": OTHER_KEY})
    assert imported.status_code == 201
    new_id = imported.json()["id"]
    replay = await api.post(f"{V}/runs/{new_id}/replay", headers={"X-API-Key": OTHER_KEY}, json={})
    assert replay.status_code == 201
    done = await wait_for_status(api.__class__(transport=api._transport, base_url="http://test",
                                               headers={"X-API-Key": OTHER_KEY}), replay.json()["id"],
                                 {"succeeded", "failed"})
    assert done["status"] == "succeeded"
    assert (await api.get(f"{V}/export/evals")).json()["evals"] == []


async def test_key_management(api):
    keys = (await api.get(f"{V}/keys")).json()
    assert [k["name"] for k in keys] == ["bootstrap"] and keys[0]["current"] and keys[0]["last_used_at"]

    created = (await api.post(f"{V}/keys", json={"name": "ci", "role": "read"})).json()
    assert created["key"].startswith("mm_") and created["prefix"] == created["key"][:10]
    listed = (await api.get(f"{V}/keys")).json()
    assert {k["name"]: k["role"] for k in listed} == {"bootstrap": "admin", "ci": "read"}
    assert all("key" not in k and "key_hash" not in k for k in listed)  # secrets are shown once

    ci = {"X-API-Key": created["key"]}
    assert (await api.get(f"{V}/runs", headers=ci)).status_code == 200
    assert (await api.get(f"{V}/keys", headers=ci)).status_code == 403  # read keys cannot manage keys
    assert (await api.post(f"{V}/keys", headers=ci, json={"name": "x"})).status_code == 403

    me = next(k for k in listed if k["current"])
    assert (await api.delete(f"{V}/keys/{me['id']}")).status_code == 409  # no self-lockout
    other_project_key = (await api.get(f"{V}/keys", headers={"X-API-Key": OTHER_KEY})).json()[0]
    assert (await api.delete(f"{V}/keys/{other_project_key['id']}")).status_code == 404
    assert (await api.delete(f"{V}/keys/{created['id']}")).status_code == 204
    assert (await api.get(f"{V}/runs", headers=ci)).status_code == 401  # revoked immediately
    assert (await api.get(f"{V}/runs", headers={"X-API-Key": API_KEY})).status_code == 200
