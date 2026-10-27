import os

from langchain_core.tools import tool

from mindmesh import ClaimCheck, MindMesh
from mindmesh.core import aio
from mindmesh.integrations.langchain import connect_langchain_agent

INVOICES = {
    "INV-1": {"vendor": "ACME", "amount": 420.00},
    "INV-2": {"vendor": "Initech", "amount": 2400.00},
    "INV-3": {"vendor": "Globex", "amount": 180.00},
}
VENDORS = {
    "ACME": {"terms": "net-30", "account": "DE89 3704 0044 0532 0130 00"},
    "Initech": {"terms": "net-15", "account": "GB33 BUKB 2020 1555 5555 55"},
}


@tool
def get_invoice(invoice_id: str) -> dict:
    """Look up an invoice and the vendor's payment details."""
    invoice = INVOICES[invoice_id]
    return {"invoice_id": invoice_id, **invoice, "vendor_details": VENDORS[invoice["vendor"]]}


@tool
def pay_invoice(invoice_id: str, amount: float) -> str:
    """Pay an invoice. This moves money."""
    return f"paid {invoice_id}: ${amount:,.2f}"


POLICIES = """
rules:
  - name: approve-large-payments
    effect: require_approval
    tools: [pay_invoice]
    conditions: [{arg: amount, op: gt, value: 1000}]
"""


def chat_model():
    from langchain_ollama import ChatOllama

    return ChatOllama(model=os.environ.get("OLLAMA_MODEL", "qwen3:4b"), temperature=0, reasoning=False,
                      format="json")


def install(mm: MindMesh) -> None:
    connect_langchain_agent(
        mm, "payables", chat_model(),
        tools=[get_invoice, pay_invoice],
        side_effects=["pay_invoice"],
        system_prompt="You pay vendor invoices. Steps: 1) call get_invoice; 2) call pay_invoice with exactly "
                      "the invoiced amount; 3) give a final answer that starts with 'PAID:' and quotes the "
                      "confirmation from pay_invoice. If get_invoice fails, do not pay: answer 'NOT PAID:' "
                      "and the reason.",
        claim_checks=[ClaimCheck(answer_regex=r"^\s*PAID", requires_tool="pay_invoice",
                                 hint="You have not called pay_invoice yet. Call it before reporting PAID.")],
    )


async def main() -> None:
    mm = await MindMesh("sqlite:///mindmesh.db").init()
    try:
        install(mm)
        await mm.load_policies(POLICIES)
        for invoice_id in INVOICES:
            run = await mm.run("payables", f"Pay invoice {invoice_id}")
            outcome = (run.result or {}).get("answer") or run.error or ""
            print(f"{invoice_id}  {run.id}  {run.status:<17} {outcome[:70]}")
    finally:
        await mm.close()


if __name__ == "__main__":
    aio.run(main())
