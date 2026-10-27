"""Invoice desk: an example MindMesh application built from a LangChain model and LangChain tools.

An accounts-payable agent pays vendor invoices. MindMesh supplies what the agent framework does not:
memory with scopes and versions, policies enforced before tools run (approval above $1,000, a hard cap),
traces with context receipts, safe replay, exports and a benchmark.

    python invoice_desk.py --reset           # seed memory + policies, then process the inbox
    MODEL=offline python invoice_desk.py     # deterministic rule-based model, no LLM needed
    mindmesh serve                           # Studio at http://127.0.0.1:8000 (run from this directory)

See README.md for the walkthrough: find why Hooli was paid despite a fraud hold, fix it, prove the fix.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool

from mindmesh import ClaimCheck, MemoryCreate, MindMesh
from mindmesh.core import aio
from mindmesh.integrations.langchain import connect_langchain_agent

AGENT = "ap-clerk"
INVOICES: dict[str, dict[str, Any]] = {
    "INV-1001": {"vendor": "ACME", "amount": 420.00, "status": "open"},
    "INV-1002": {"vendor": "Initech", "amount": 2400.00, "status": "open"},
    "INV-1003": {"vendor": "ACME", "amount": 420.00, "status": "paid"},  # a duplicate of an earlier invoice
    "INV-1004": {"vendor": "Hooli", "amount": 860.00, "status": "open"},  # vendor is on a fraud hold
    "INV-1005": {"vendor": "Umbrella", "amount": 25000.00, "status": "open"},  # above the payment cap
}
INBOX = list(INVOICES)
PAYMENTS: list[dict[str, Any]] = []
REVIEWS: list[dict[str, Any]] = []

POLICIES = """
rules:
  - name: approve-large-payments
    description: Payments above $1,000 need a human decision.
    effect: require_approval
    tools: [pay_invoice]
    conditions: [{arg: amount, op: gt, value: 1000}]
  - name: payment-cap
    description: Nothing above $10,000 is paid by an agent.
    effect: deny
    tools: [pay_invoice]
    conditions: [{arg: amount, op: gt, value: 10000}]
    priority: 10
"""

HOLD_NOTICE = ("Vendor Hooli is on payment hold: a bank-detail change failed verification (fraud alert, "
               "ticket SEC-88). Do not pay Hooli invoices; flag them for review.")


# ------------------------------------------------------------------------------------------- tools


@tool
def get_invoice(invoice_id: str) -> dict:
    """Look up an invoice: vendor, amount and status (open or paid)."""
    if invoice_id not in INVOICES:
        raise ValueError(f"unknown invoice {invoice_id}")
    return {"invoice_id": invoice_id, **INVOICES[invoice_id]}


@tool
def pay_invoice(invoice_id: str, amount: float) -> str:
    """Pay an open invoice. This moves money."""
    PAYMENTS.append({"invoice_id": invoice_id, "amount": amount})
    INVOICES[invoice_id]["status"] = "paid"
    return f"payment PAY-{len(PAYMENTS):04d}: {invoice_id} ${amount:,.2f}"


@tool
def flag_for_review(invoice_id: str, reason: str) -> str:
    """Send an invoice to a human reviewer instead of paying it."""
    REVIEWS.append({"invoice_id": invoice_id, "reason": reason})
    return f"review REV-{len(REVIEWS):04d} opened for {invoice_id}"


SYSTEM_PROMPT = """You are an accounts-payable clerk. For the invoice in the task:
1) call get_invoice;
2) if its status is "paid", do not pay again: answer "NOT PAID: duplicate";
3) if the CONTEXT says the vendor is on a payment hold, call flag_for_review and answer "FLAGGED: <reason>";
4) otherwise call pay_invoice with exactly the invoiced amount and answer "PAID: <payment confirmation>".
If a tool call is blocked or fails, answer "NOT PAID: <reason>"."""


# ------------------------------------------------------------------------------------------- models


class RuleBasedClerk(BaseChatModel):
    """A deterministic LangChain chat model that follows SYSTEM_PROMPT by reading the prompt MindMesh built.

    It sees exactly what an LLM would (assembled context, tool results), so the example and its benchmark run
    offline and reproducibly. Swap in any real chat model with ``MODEL=ollama:<model>``."""

    @property
    def _llm_type(self) -> str:
        return "rule-based-clerk"

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        action = self._decide(messages)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(json.dumps(action)))])

    @staticmethod
    def _decide(messages: list[BaseMessage]) -> dict[str, Any]:
        system, task = str(messages[0].content), str(messages[1].content)
        invoice_id = re.search(r"INV-\d+", task).group(0)
        results = {}
        for m in messages[2:]:
            hit = re.match(r"RESULT of (\S+): (.*)", str(m.content), re.S)
            if hit:
                results[hit.group(1)] = json.loads(hit.group(2))

        def answer(text: str) -> dict[str, Any]:
            return {"type": "final_answer", "thought": text, "answer": text}

        def call(tool_name: str, **args: Any) -> dict[str, Any]:
            return {"type": "tool_call", "thought": f"call {tool_name}", "tool": tool_name, "args": args}

        if "get_invoice" not in results:
            return call("get_invoice", invoice_id=invoice_id)
        inv = results["get_invoice"]
        if inv["status"] != "ok":
            return answer(f"NOT PAID: {inv.get('error')}")
        inv = inv["result"]
        context = system.split("CONTEXT:", 1)[-1]
        if inv["status"] == "paid":
            return answer("NOT PAID: duplicate (invoice already paid)")
        if "flag_for_review" in results:
            return answer(f"FLAGGED: {results['flag_for_review'].get('result')}")
        if re.search(rf"{inv['vendor']} is on payment hold", context):
            return call("flag_for_review", invoice_id=invoice_id, reason=f"{inv['vendor']} is on payment hold")
        if "pay_invoice" not in results:
            return call("pay_invoice", invoice_id=invoice_id, amount=inv["amount"])
        paid = results["pay_invoice"]
        if paid["status"] != "ok":
            return answer(f"NOT PAID: {paid.get('error') or paid['status']}")
        return answer(f"PAID: {paid['result']}")


def chat_model() -> BaseChatModel:
    model = os.environ.get("MODEL", "ollama:qwen3:4b")
    if model == "offline":
        return RuleBasedClerk()
    if model.startswith("ollama:"):
        from langchain_ollama import ChatOllama

        return ChatOllama(model=model.split(":", 1)[1], temperature=0, reasoning=False, format="json")
    raise ValueError(f"MODEL must be 'offline' or 'ollama:<model>', not {model!r} (or edit chat_model())")


# ---------------------------------------------------------------------------------------- app wiring


def install(mm: MindMesh) -> None:
    """Register tools and the agent (used by this script, `mindmesh serve` and `mindmesh runs rerun --app`)."""
    connect_langchain_agent(
        mm, AGENT, chat_model(),
        tools=[get_invoice, pay_invoice, flag_for_review],
        side_effects=["pay_invoice", "flag_for_review"],
        system_prompt=SYSTEM_PROMPT,
        memory_scopes=["project", f"agent:{AGENT}"],
        claim_checks=[ClaimCheck(answer_regex=r"^\s*PAID", requires_tool="pay_invoice",
                                 hint="You have not called pay_invoice; call it before answering PAID.")],
    )


async def seed(mm: MindMesh, *, memory_state: str = "broken") -> None:
    """Payment rules in memory + policies. ``broken`` reproduces the incident: security filed the Hooli hold
    in the security team's private scope, where the clerk never sees it."""
    from mindmesh.demo.showcase import reset_project

    await reset_project(mm)
    await mm.load_policies(POLICIES)
    await mm.memory.add(MemoryCreate(content="Payment terms: ACME net-30, Initech net-15, Hooli net-30, Umbrella net-60.",
                                     subject_key="payment_terms", kind="fact", trust=0.9))
    await mm.memory.add(MemoryCreate(content=HOLD_NOTICE, subject_key="vendor_hold:hooli", kind="fact",
                                     trust=0.95, importance=0.9,
                                     scope="project" if memory_state == "fixed" else "agent:security"))


def reset_world() -> None:
    PAYMENTS.clear()
    REVIEWS.clear()
    for invoice_id, invoice in INVOICES.items():
        invoice["status"] = "paid" if invoice_id == "INV-1003" else "open"


# Benchmark hooks (invoice_desk.yaml): a fresh world and database per task.
async def eval_setup(mm: MindMesh, *, memory_state: str, faults: dict[str, int]) -> None:
    reset_world()
    install(mm)
    await seed(mm, memory_state=memory_state)


def eval_task(task) -> tuple[str, dict[str, Any]]:
    return task.task, task.input


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--reset", action="store_true", help="re-seed memory and policies (broken state)")
    parser.add_argument("--db", default=os.environ.get("MINDMESH_DATABASE_URL", "sqlite:///mindmesh.db"))
    args = parser.parse_args()
    mm = await MindMesh(args.db).init()
    try:
        install(mm)
        if args.reset or not await mm.repos.policies.list():
            await seed(mm)
        for invoice_id in INBOX:
            run = await mm.run(AGENT, f"Process invoice {invoice_id}")
            outcome = (run.result or {}).get("answer") or run.error or ""
            print(f"{invoice_id}  {run.id}  {run.status:<17} {outcome[:60]}")
        print(f"payments made: {PAYMENTS}")
    finally:
        await mm.close()


if __name__ == "__main__":
    aio.run(main())
