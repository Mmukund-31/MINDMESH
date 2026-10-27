"""The quickstart (docs/quickstart.md) and the invoice desk example work as documented."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("langchain_core")

from langchain_core.language_models.fake_chat_models import FakeListChatModel  # noqa: E402

from mindmesh import MindMesh  # noqa: E402
from mindmesh.export import export_run, import_run  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def _load(path: Path, name: str):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_quickstart_doc_matches_the_tested_agent():
    import re

    section = (ROOT / "docs" / "quickstart.md").read_text(encoding="utf-8").split("## 2. Write the agent", 1)[1]
    code = re.search(r"```python\n(.*?)```", section, re.S).group(1)
    assert code == (ROOT / "examples" / "quickstart" / "my_agent.py").read_text(encoding="utf-8")


def _act(tool=None, answer=None, **args):
    if tool:
        return json.dumps({"type": "tool_call", "thought": "", "tool": tool, "args": args})
    return json.dumps({"type": "final_answer", "thought": "", "answer": answer})


async def test_quickstart_flow(db_url, tmp_path, monkeypatch):
    """Run -> approval pause -> failure from the agent's own bug -> export -> replay elsewhere -> fix -> rerun."""
    agent = _load(ROOT / "examples" / "quickstart" / "my_agent.py", "my_agent")
    responses = [  # what qwen3:4b did in the recorded quickstart session
        _act("get_invoice", invoice_id="INV-1"), _act("pay_invoice", invoice_id="INV-1", amount=420.0),
        _act(answer='PAID: "paid INV-1: $420.00"'),
        _act("get_invoice", invoice_id="INV-2"), _act("pay_invoice", invoice_id="INV-2", amount=2400.0),
        _act("get_invoice", invoice_id="INV-3"), _act(answer="NOT PAID: KeyError: 'Globex'"),
    ]
    monkeypatch.setattr(agent, "chat_model", lambda: FakeListChatModel(responses=responses))
    mm = await MindMesh(db_url).init()
    try:
        agent.install(mm)
        await mm.load_policies(agent.POLICIES)
        runs = {i: await mm.run("payables", f"Pay invoice {i}") for i in agent.INVOICES}
        assert runs["INV-1"].result["answer"].startswith("PAID")
        assert runs["INV-2"].status == "waiting_approval"
        failed = runs["INV-3"]
        step1 = (await mm.repos.events.list(failed.id, types=["step.finished"]))[0]
        assert "KeyError: 'Globex'" in json.dumps(step1.payload)  # the trace pinpoints the agent's own bug

        doc = json.loads(json.dumps(await export_run(mm, failed.id)))
        teammate = await MindMesh(f"sqlite:///{tmp_path / 'teammate.db'}", project="triage").init()
        try:
            copy = await import_run(teammate, doc)
            replay = await teammate.replay(copy.id)
            assert replay.result["answer"] == failed.result["answer"]  # reproduced without the agent's code
        finally:
            await teammate.close()

        agent.VENDORS["Globex"] = {"terms": "net-30", "account": "FR76"}  # the fix, in the agent's own code
        monkeypatch.setattr(agent, "chat_model", lambda: FakeListChatModel(responses=[
            _act("get_invoice", invoice_id="INV-3"), _act("pay_invoice", invoice_id="INV-3", amount=180.0),
            _act(answer='PAID: "paid INV-3: $180.00"')]))
        agent.install(mm)
        fixed = await mm.rerun(failed.id)
        assert fixed.result["answer"].startswith("PAID")
        assert (await mm.compare(failed.id, fixed.id))["divergence_step"] is not None
    finally:
        await mm.close()


def _run(args, cwd, **env):
    full = {**os.environ, "PYTHONIOENCODING": "utf-8", "MODEL": "offline", **env}
    return subprocess.run([sys.executable, *args], cwd=cwd, env=full, capture_output=True, text=True, encoding="utf-8", timeout=300)


def test_invoice_desk_example_offline(tmp_path):
    app_dir = ROOT / "examples" / "invoice_desk"
    db = f"sqlite:///{tmp_path / 'desk.db'}"
    out = _run(["invoice_desk.py", "--reset", "--db", db], app_dir)
    assert out.returncode == 0, out.stderr
    lines = {ln.split()[0]: ln for ln in out.stdout.splitlines() if ln.startswith("INV-")}
    assert "PAID" in lines["INV-1001"] and "waiting_approval" in lines["INV-1002"]
    assert "duplicate" in lines["INV-1003"] and "blocked by policy" in lines["INV-1005"]
    assert "PAID" in lines["INV-1004"]  # the incident the README walks through: a vendor on a fraud hold paid

    bench = _run(["-m", "mindmesh.cli", "bench", "--suite", "invoice_desk.yaml", "--out", str(tmp_path / "bench")],
                 app_dir, MINDMESH_DATABASE_URL=db)
    assert bench.returncode == 0, bench.stderr
    export = _run(["-m", "mindmesh.cli", "evals", "export", "--suite", "invoice_desk"], app_dir,
                  MINDMESH_DATABASE_URL=db)
    doc = json.loads(export.stdout)
    rates = {e["variant"]: e["metrics"]["success_rate"] for e in doc["evals"]}
    assert rates == {"prompt-only": 0.8, "mindmesh-misconfigured": 0.8, "mindmesh": 1.0}


async def test_invoice_desk_incident_replays_without_the_agent(tmp_path, monkeypatch):
    """A claim-checked, side-effecting run replays in a database where the agent's tools are not registered."""
    monkeypatch.setenv("MODEL", "offline")
    desk = _load(ROOT / "examples" / "invoice_desk" / "invoice_desk.py", "invoice_desk")
    mm = await MindMesh(f"sqlite:///{tmp_path / 'desk.db'}").init()
    other = await MindMesh(f"sqlite:///{tmp_path / 'teammate.db'}", project="triage").init()
    try:
        desk.reset_world()
        desk.install(mm)
        await desk.seed(mm)
        incident = await mm.run(desk.AGENT, "Process invoice INV-1004")
        assert incident.result["answer"].startswith("PAID")  # paid a vendor on a fraud hold
        copy = await import_run(other, json.loads(json.dumps(await export_run(mm, incident.id))))
        payments = len(desk.PAYMENTS)
        replay = await other.replay(copy.id)
        assert replay.status == "succeeded" and replay.result["answer"] == incident.result["answer"]
        cmp = await other.compare(copy.id, replay.id)
        assert all(s["same_action"] for s in cmp["steps"])
        assert [s["b"]["outcome"]["status"] for s in cmp["steps"]] == ["ok", "ok", "final"]
        assert len(desk.PAYMENTS) == payments  # nothing was executed
    finally:
        await mm.close()
        await other.close()
