# Quickstart: connect a real agent in 10 minutes

You will take a small LangChain agent that pays invoices and run it under MindMesh with a real LLM. Then you
will:

- inspect what it did, step by step;
- find a bug in your own tool code from the trace;
- hand the failure to a teammate who replays it exactly, without your code or a model;
- fix the bug and prove the fix.

None of this changes MindMesh itself.

**You need:** Python 3.12+ and a chat model. The steps use [Ollama](https://ollama.com) with `qwen3:4b`, which
is free, local and runs on a laptop GPU or CPU. Any LangChain chat model works: see step 2.

## 1. Install (2 min)

```bash
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install "mindmesh[server,langchain] @ git+https://github.com/Mmukund-31/MINDMESH.git" langchain-ollama
ollama pull qwen3:4b
```

The package includes the API server, the Studio UI and the `mindmesh` CLI. Nothing else needs to be installed.

## 2. Write the agent (2 min)

Save this as `my_agent.py`. It is plain LangChain: two `@tool` functions and a chat model. The only MindMesh
part is `connect_langchain_agent`, which registers them. MindMesh then drives the loop, so every tool call is
validated, checked against your policies and traced before it runs.

```python
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
```

What MindMesh adds here:

- **`side_effects`** marks `pay_invoice` as moving money. It is never retried blindly and never re-executed
  during replay.
- **The policy** pauses any payment above $1,000 for a human. It is enforced in code, not in the prompt.
- **`claim_checks`** catches a small model reporting `PAID` without calling `pay_invoice`. Without it,
  `qwen3:4b` sometimes answers with just the amount.

**Using another model:** replace `chat_model()` with any LangChain chat model, for example
`ChatOpenAI(model="gpt-4o-mini")` from `langchain-openai`, or `ChatAnthropic(...)` from `langchain-anthropic`.

## 3. Run it (1 min)

```bash
python my_agent.py
```

```
INV-1  run_01m5yn2atchq0xsntz648r  succeeded         PAID: "paid INV-1: $420.00"
INV-2  run_01m5yn2fcs85fj0j37zbwh  waiting_approval
INV-3  run_01m5yn2hp88pc7qtawg302  succeeded         NOT PAID: KeyError: 'Globex'
```

INV-2 is waiting for a human, as the policy requires. INV-3 was not paid. Next you'll find out why.

## 4. Inspect the execution (2 min)

**In the terminal:**

```bash
mindmesh runs list
mindmesh runs show run_01m5yn2hp88pc7qtawg302
```

```
  step   action         args                      outcome
  1      get_invoice    {'invoice_id': 'INV-3'}   error - KeyError: 'Globex'
  2      final_answer                             final
```

The trace pinpoints it: `get_invoice` crashed, because `VENDORS` has no entry for Globex. That's a bug in your
tool, not the model's fault.

**In Studio:** run `MINDMESH_APPS=my_agent mindmesh serve` and open http://127.0.0.1:8000.

- **Execution Studio** shows each run's graph, model calls, tool calls, policy decisions and the exact
  context the model saw.
- **Control Room** lists INV-2's pending approval. Approve it, and the run resumes and pays.

`MINDMESH_APPS=my_agent` loads your agent into the server, so approved runs can continue.

## 5. Reproduce the failure somewhere else (2 min)

Export the run as JSON and give the file to a teammate (or attach it to an issue):

```bash
mindmesh runs export run_01m5yn2hp88pc7qtawg302 -o inv3-failure.json
```

On the teammate's machine, with an empty database, no `my_agent.py` and no model:

```bash
mindmesh runs import inv3-failure.json -p triage
mindmesh runs replay <imported run id> -p triage
```

```
replay run_01m5yn43y56bjjppjh8xf1: succeeded -> NOT PAID: KeyError: 'Globex'
reproduced the original run: same actions, outcomes and answer
```

A safe replay feeds the recorded model outputs and tool results back through the runtime. Nothing is executed,
so the failure is reproduced exactly, even though LLM output is normally non-deterministic. The format is
described in [export-format.md](export-format.md).

## 6. Fix it and prove the fix (1 min)

Add the missing vendor to `VENDORS` in `my_agent.py`:

```python
    "Globex": {"terms": "net-30", "account": "FR76 3000 6000 0112 3456 7890 189"},
```

Then rerun the failed run live, with your fixed code and the real model:

```bash
mindmesh runs rerun run_01m5yn2hp88pc7qtawg302 --app my_agent
```

```
rerun run_01m5yn3j8atar5x0prccw0: succeeded -> PAID: "paid INV-3: $180.00"
first divergence at step 2
```

**Replay Lab** in Studio shows the original and the rerun side by side.

## Where next

- [examples/invoice_desk](../examples/invoice_desk): a complete example app with memory, policies as code,
  an incident to diagnose from a context receipt, and a benchmark you can export as JSON.
- [SDK guide](sdk.md): tools, agents, memory, policies, workflows.
- [LangChain integration](integrations/langchain.md): what maps to what, and its limits.
- `mindmesh --help`: projects, keys, runs, evals, benchmarks.
