"""Security properties: tenant isolation, authentication, enforcement outside the LLM,
argument validation and secret handling."""

import json

import pytest

from mindmesh import AgentSpec, MemoryCreate
from mindmesh.core.types import Condition, PolicyEffect, PolicyRuleIn
from mindmesh.demo import refund
from mindmesh.models.scripted import ScriptedProvider

from ..conftest import OTHER_KEY, wait_for_status

V = "/api/v1"


async def test_requests_without_or_with_bad_key_are_rejected(api):
    assert (await api.get(f"{V}/runs", headers={"X-API-Key": ""})).status_code == 401
    assert (await api.get(f"{V}/runs", headers={"X-API-Key": "mm_wrong_key_000000000000"})).status_code == 401
    ok = await api.get(f"{V}/me", headers={"X-API-Key": "", "Authorization": f"Bearer {OTHER_KEY}"})
    assert ok.status_code == 200 and ok.json()["project_name"] == "bravo"


async def test_cross_project_access_is_404(api):
    await refund.seed(api.app.state.mm, memory_state="broken")
    task, inp = refund.task_for("C-3310", "A-9555")
    run = (await api.post(f"{V}/runs", json={"agent": "support", "task": task, "input": inp})).json()
    await wait_for_status(api, run["id"], {"succeeded"})
    mem = (await api.get(f"{V}/memories")).json()[0]
    other = {"X-API-Key": OTHER_KEY}
    for path in (f"/runs/{run['id']}", f"/runs/{run['id']}/trace", f"/runs/{run['id']}/events",
                 f"/memories/{mem['id']}", f"/memories/{mem['id']}/versions"):
        assert (await api.get(V + path, headers=other)).status_code == 404, path
    assert (await api.post(f"{V}/runs/{run['id']}/rerun", headers=other, json={})).status_code == 404
    assert (await api.post(f"{V}/runs/{run['id']}/cancel", headers=other)).status_code == 404
    assert (await api.patch(f"{V}/memories/{mem['id']}", headers=other, json={"content": "pwned"})).status_code == 404
    assert (await api.get(f"{V}/runs", headers=other)).json() == []
    assert (await api.get(f"{V}/memories", headers=other)).json() == []
    # memories of another project never enter context
    bravo = api.app.state.mm.scoped(await api.app.state.mm.db.ensure_project("bravo"))
    rc = await bravo.context.assemble(query="refund policy", config=bravo.agents["support"].context, scopes=["project"])
    assert [i for i in rc.included if i.kind == "memory"] == []


async def test_approvals_cannot_be_resolved_across_projects(api):
    await refund.seed(api.app.state.mm, memory_state="broken")
    task, inp = refund.task_for("C-2077", "A-9020")
    run = (await api.post(f"{V}/runs", json={"agent": "support", "task": task, "input": inp})).json()
    await wait_for_status(api, run["id"], {"waiting_approval"})
    [appr] = (await api.get(f"{V}/approvals", params={"status": "pending"})).json()
    r = await api.post(f"{V}/approvals/{appr['id']}/resolve", headers={"X-API-Key": OTHER_KEY}, json={"approve": True})
    assert r.status_code == 404
    assert (await api.get(f"{V}/runs/{run['id']}")).json()["status"] == "waiting_approval"


async def test_denied_tool_never_executes(mm):
    executed = []

    @mm.tool(side_effect=True)
    def delete_db(name: str) -> str:
        executed.append(name)
        return "deleted"

    def evil(req):
        if not req.history:
            return {"type": "tool_call", "tool": "delete_db", "args": {"name": "prod"}}
        return {"type": "final_answer", "answer": req.history[-1]["outcome"]["status"]}

    mm.register_provider_instance("scripted:evil", ScriptedProvider("evil", evil))
    mm.agent(AgentSpec(name="evil", tools=["delete_db"], model="scripted:evil"))
    await mm.add_policy(PolicyRuleIn(name="never-prod", effect=PolicyEffect.DENY, tools=["delete_db"],
                                     conditions=[Condition(arg="name", op="eq", value="prod")]))
    run = await mm.run("evil", "clean up")
    assert executed == [] and run.result["answer"] == "blocked"


async def test_tools_outside_allowlist_never_execute_even_if_model_asks(mm):
    executed = []

    @mm.tool()
    def secret_tool() -> str:
        executed.append(1)
        return "x"

    @mm.tool()
    def harmless() -> str:
        return "y"

    mm.register_provider_instance("scripted:sneaky", ScriptedProvider("sneaky", lambda req: (
        {"type": "tool_call", "tool": "secret_tool", "args": {}} if not req.history
        else {"type": "final_answer", "answer": req.history[-1]["outcome"]["status"]})))
    mm.agent(AgentSpec(name="sneaky", tools=["harmless"], model="scripted:sneaky"))
    run = await mm.run("sneaky", "t")
    assert executed == [] and run.result["answer"] == "blocked"


@pytest.mark.parametrize("args", [
    {"path": "/data/x", "mode": "rw"},           # unknown field
    {"path": 123},                                # wrong type, no coercion
    {},                                           # missing field
])
async def test_tool_argument_validation(mm, args):
    seen = []

    @mm.tool()
    def read_file(path: str) -> str:
        seen.append(path)
        return "content"

    mm.register_provider_instance("scripted:r", ScriptedProvider("r", lambda req: (
        {"type": "tool_call", "tool": "read_file", "args": args} if not req.history
        else {"type": "final_answer", "answer": req.history[-1]["outcome"]["status"]})))
    mm.agent(AgentSpec(name="r", tools=["read_file"], model="scripted:r"))
    run = await mm.run("r", "t")
    assert seen == [] and run.result["answer"] == "invalid_args"


async def test_path_traversal_is_blocked_by_path_policy(mm):
    seen = []

    @mm.tool()
    def read_file(path: str) -> str:
        seen.append(path)
        return "content"

    mm.register_provider_instance("scripted:t", ScriptedProvider("t", lambda req: (
        {"type": "tool_call", "tool": "read_file", "args": {"path": "/srv/data/../../etc/shadow"}} if not req.history
        else {"type": "final_answer", "answer": req.history[-1]["outcome"]["status"]})))
    mm.agent(AgentSpec(name="t", tools=["read_file"], model="scripted:t"))
    await mm.add_policy(PolicyRuleIn(name="sandbox", effect=PolicyEffect.DENY, tools=["read_file"],
                                     conditions=[Condition(arg="path", op="not_path_prefix", value="/srv/data")]))
    run = await mm.run("t", "t")
    assert seen == [] and run.result["answer"] == "blocked"


async def test_secrets_in_memory_api_responses_are_not_logged(api):
    mm = api.app.state.mm
    await mm.memory.add(MemoryCreate(content="Escalation contact: ops@example.com"))
    # API keys are stored hashed only
    from sqlalchemy import select

    from mindmesh.storage.orm import ApiKeyRow
    async with mm.db.session() as s:
        hashes = [r.key_hash for r in (await s.execute(select(ApiKeyRow))).scalars()]
    assert OTHER_KEY not in json.dumps(hashes) and all(len(h) == 64 for h in hashes)
