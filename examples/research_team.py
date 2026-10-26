"""Multi-agent workflow: planner -> two parallel researchers -> writer -> verifier (rejects once)."""

import asyncio

from mindmesh import MindMesh
from mindmesh.demo import research


async def main():
    mm = await MindMesh("sqlite:///research.db", project="research").init()
    research.install(mm)
    research.reset_faults()
    wid = await mm.run_workflow(research.TEMPLATE)
    print("workflow", wid, (await mm.repos.workflows.get_run(wid)).status)
    for t in await mm.repos.workflows.tasks(wid):
        print(f"  {t.key:<14} {t.status:<10} attempts={t.attempts}  {(t.output or {}).get('answer', '')[:80]}")
    for e in await mm.repos.events.list(wid):
        if e.type in ("handoff", "verifier.rejected", "verifier.approved"):
            print("  ·", e.type, e.payload)
    await mm.close()


if __name__ == "__main__":
    asyncio.run(main())
