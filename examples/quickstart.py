"""Minimal MINDMESH integration: memory + enforced policy + human approval + trace.

    python examples/quickstart.py                 # deterministic scripted model
    MODEL=ollama:qwen3:8b python examples/quickstart.py
"""

import asyncio
import os

from mindmesh import AgentSpec, Condition, MindMesh, PolicyRuleIn, brain


@brain("treasurer")
def treasurer(req):
    """Scripted stand-in for an LLM: reads the vendor terms from context, then pays."""
    terms = next((c.content for c in req.context if "ACME" in c.content), None)
    if not req.history:
        return {"type": "tool_call", "thought": f"Terms: {terms}", "tool": "pay",
                "args": {"recipient": "ACME", "amount": 1500.0}}
    outcome = req.history[-1]["outcome"]
    return {"type": "final_answer", "answer": f"payment {outcome['status']}: {outcome.get('result') or outcome.get('error')}"}


async def main():
    mm = await MindMesh("sqlite:///quickstart.db", project="quickstart").init()

    @mm.tool(side_effect=True, description="Send money to a recipient")
    async def pay(recipient: str, amount: float) -> dict:
        return {"transfer_id": "TX-1", "recipient": recipient, "amount": amount}

    mm.agent(AgentSpec(name="treasurer", tools=["pay"], model=os.environ.get("MODEL", "scripted:treasurer")))
    await mm.remember("Vendor ACME is paid net-30 by bank transfer.", subject_key="acme_terms")
    await mm.repos.policies.replace_all([PolicyRuleIn(
        name="approve-large-payments", effect="require_approval", tools=["pay"],
        conditions=[Condition(arg="amount", op="gt", value=1000)],
    )])

    run = await mm.run("treasurer", "Pay ACME's invoice #12 for $1,500")
    print("status:", run.status)                                   # waiting_approval
    [approval] = await mm.repos.approvals.list(status="pending", run_id=run.id)
    print("approval needed:", approval.tool, approval.args, "-", approval.reason)
    _, run = await mm.resolve_approval(approval.id, approve=True, resolver="cfo")
    print("result:", run.result["answer"])
    for e in await mm.repos.events.list(run.id):
        print(f"  #{e.seq:<3} {e.type:<20} step={e.step}")
    await mm.close()


if __name__ == "__main__":
    asyncio.run(main())
