"""Persistence across a real PostgreSQL server restart (used by CI).

    python -m tests.integration.pg_restart_check write    # migrate, seed, run an agent; save expectations
    docker restart <postgres container>
    python -m tests.integration.pg_restart_check verify   # new process: everything is still there

Reads MINDMESH_TEST_DATABASE_URL. Expectations are kept in ``pg_restart_state.json`` in the current directory.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mindmesh import MindMesh
from mindmesh.demo import refund
from mindmesh.storage.db import head_revision

STATE = Path("pg_restart_state.json")
PROJECT = "restart-check"


async def write(url: str) -> dict:
    mm = await MindMesh(url, project=PROJECT).init()
    try:
        refund.install(mm)
        ids = await refund.seed(mm, memory_state="broken")
        task, inp = refund.task_for("C-1042", "A-7731")
        run = await mm.run("support", task, inp)
        key = await mm.db.create_api_key(mm.project_id, "restart-check")
        return {
            "project_id": mm.project_id, "run_id": run.id, "answer": run.result["answer"],
            "events": len(await mm.repos.events.list(run.id)), "memory_id": ids["new_policy"], "key": key,
        }
    finally:
        await mm.close()


async def verify(url: str, want: dict) -> None:
    mm = await MindMesh(url, project=PROJECT).init()
    try:
        assert await mm.db.current_revision() == head_revision(), "schema revision lost"
        assert mm.project_id == want["project_id"], "project re-created"
        assert await mm.db.project_for_key(want["key"]) == want["project_id"], "API key lost"
        run = await mm.repos.runs.get(want["run_id"])
        assert run.result["answer"] == want["answer"], "run result changed"
        assert len(await mm.repos.events.list(run.id)) == want["events"], "events lost"
        assert (await mm.memory.get(want["memory_id"])).content, "memory lost"
        hits = await mm.memory.search("refund window premium", k=3)
        assert hits and hits[0].similarity > 0, "vector search returned nothing after restart"
    finally:
        await mm.close()


def main() -> None:
    url = os.environ.get("MINDMESH_TEST_DATABASE_URL", "")
    if not url.startswith("postgres") or len(sys.argv) != 2 or sys.argv[1] not in ("write", "verify"):
        sys.exit("usage: MINDMESH_TEST_DATABASE_URL=postgresql://… python -m tests.integration.pg_restart_check "
                 "write|verify")
    if sys.argv[1] == "write":
        state = asyncio.run(write(url))
        STATE.write_text(json.dumps(state))
        print(f"wrote run {state['run_id']}")
    else:
        asyncio.run(verify(url, json.loads(STATE.read_text())))
        print("all data present after restart")


if __name__ == "__main__":
    main()
