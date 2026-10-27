# Invoice desk: an example MindMesh application

A small accounts-payable agent built from **LangChain** parts (a chat model and three `@tool` functions) and
run under **MindMesh**. It shows what a production agent needs beyond the framework:

| | Where |
|---|---|
| Payment rules the agent must know (vendor holds, terms) | **memory**, with scopes and versions |
| Rules the agent must not break (approval above $1,000, hard cap at $10,000) | **policies as code** (`POLICIES`), enforced before a tool runs |
| What the agent saw and did, step by step | **traces** with context receipts, in Studio or `mindmesh runs show` |
| Proof that a fix works, and that it stays fixed | **rerun + compare**, and a **benchmark** (`invoice_desk.yaml`) |
| Sharing a failure | **JSON export / import / safe replay** |

## Run it

From this directory, after the [quickstart](../../docs/quickstart.md) installation (`pip install
"mindmesh[server,langchain] @ git+https://github.com/Mmukund-31/MINDMESH.git" langchain-ollama`):

```bash
python invoice_desk.py --reset                  # real model: Ollama qwen3:4b (MODEL=ollama:<model> to change)
MODEL=offline python invoice_desk.py --reset    # or: deterministic rule-based model, no LLM needed
```

```
INV-1001  run_…  succeeded         PAID: payment PAY-0001: INV-1001 $420.00
INV-1002  run_…  waiting_approval
INV-1003  run_…  succeeded         NOT PAID: duplicate (invoice already paid)
INV-1004  run_…  succeeded         PAID: payment PAY-0002: INV-1004 $860.00
INV-1005  run_…  succeeded         NOT PAID: blocked by policy: Nothing above $10,000 is paid by an agent.
```

The results, invoice by invoice:

- **INV-1002** waits for a human (the approval policy).
- **INV-1003** is a duplicate, so it is not paid.
- **INV-1005** is above the cap. The policy blocks the call before `pay_invoice` executes, whatever the model
  decided.
- **INV-1004 is the incident.** Security put Hooli on a fraud hold, but the agent paid it anyway.

`MODEL=offline` uses `RuleBasedClerk`, a LangChain chat model that follows the system prompt deterministically
by reading the same prompt an LLM gets. CI uses it, and it makes the walkthrough below reproducible. With a
real model, the agent's wording varies but the incident does not: the model never sees the hold.

## Diagnose the incident

```bash
MINDMESH_APPS=invoice_desk mindmesh serve       # Studio at http://127.0.0.1:8000
```

Open the INV-1004 run in **Execution Studio** and go to **Context receipts**. The same receipt is printed by
`mindmesh runs show <run id>`:

```
✘  vendor_hold:hooli  agent:security  0.53  scope_mismatch scope 'agent:security' not in ['project', 'agent:ap-clerk']
```

The hold notice exists, but it was filed in the security team's private scope. The clerk's context excluded it,
so the model never saw it. The model did nothing wrong, and neither did the policies. The data was in the wrong
place.

## Fix it, and prove the fix

1. In **Memory Explorer**, open `vendor_hold:hooli` and change its scope to `project`. Use **Preview impact**
   first: it shows the INV-1004 run would now include the notice. Applying the change creates version 2 of the
   memory; version 1 stays in the history.
2. Back on the INV-1004 run, click **Rerun**. The agent now calls `flag_for_review` and answers `FLAGGED`.
   **Compare with parent** shows the decisions diverging at step 2, with the hold notice added to the context.

The same fix with the SDK:
`await mm.memory.update(memory_id, MemoryUpdate(scope="project", reason="holds apply to all payers"))`.

## Benchmark it and export the results

The suite runs every task against three variants, each in a fresh database: a typical "rules in the prompt"
stack, MindMesh as misconfigured during the incident, and MindMesh after the fix.

```bash
MODEL=offline mindmesh bench --suite invoice_desk.yaml
mindmesh evals export --suite invoice_desk -o results.json      # mindmesh.eval/v1 JSON
```

| | prompt-only | mindmesh-misconfigured | mindmesh |
|---|---|---|---|
| task success | 80% | 80% | 100% |
| failure | paid the $25,000 invoice | paid the vendor on hold | none |

To evaluate a real model on the same tasks, run `MODEL=ollama:qwen3:4b mindmesh bench --suite invoice_desk.yaml`.

## Share a failure

```bash
mindmesh runs export <INV-1004 run id> -o hooli-incident.json
# on another machine: no invoice_desk.py, no model
mindmesh runs import hooli-incident.json -p triage && mindmesh runs replay <imported id> -p triage
```

## Files

- `invoice_desk.py`: the tools, the models, `install(mm)` (also used by `mindmesh serve`/`rerun --app`),
  `seed(mm)` for memory and policies, and the benchmark hooks `eval_setup`/`eval_task`.
- `invoice_desk.yaml`: the benchmark suite.
- `tests/integration/test_examples.py` (repository root): runs this example and its benchmark in CI.
