# LangChain integration

`mindmesh.integrations.langchain` runs a LangChain agent's **model** and **tools** under MindMesh. Install it
with `pip install "mindmesh[langchain]"` plus the provider package you use (`langchain-ollama`,
`langchain-openai`, `langchain-anthropic`, …).

```python
from langchain_openai import ChatOpenAI
from mindmesh.integrations.langchain import connect_langchain_agent

connect_langchain_agent(mm, "researcher", ChatOpenAI(model="gpt-4o-mini", temperature=0),
                        tools=[search, fetch_page, save_note], side_effects=["save_note"],
                        system_prompt="…", limits=Limits(max_steps=10))
run = await mm.run("researcher", "Summarise this week's pgvector releases")
```

## Why this shape

MindMesh's value is in the loop: deciding what context the model sees, checking every tool call against
policies *before* it runs, pausing for approvals, recording each step so it can be replayed, and recovering
from crashes. If MindMesh only observed a LangChain loop from the outside, it could trace tool calls but
couldn't block them, pause them or replay them. So MindMesh drives the loop, and LangChain supplies the two
parts it is best at: chat-model clients for every provider, and its tool ecosystem.

| LangChain | MindMesh |
|---|---|
| a chat model (`BaseChatModel`) | a model provider: `LangChainProvider(chat_model)`, pinned under the model spec `langchain:<agent>` |
| a tool (`BaseTool`, `@tool`) | a MindMesh tool: `add_langchain_tool(mm, tool, side_effect=…, transient_errors=(…))`. Its `args_schema` becomes the strict argument model (unknown fields rejected) |
| the agent's prompt | `AgentSpec.system_prompt`. MindMesh appends the tool list, the assembled context and its JSON action protocol |
| — | `AgentSpec` fields such as `limits`, `context`, `memory_scopes` and `claim_checks` pass through `connect_langchain_agent(**fields)` |

## Behaviour

- **Any chat model works**, including ones without native tool calling. The model replies with one JSON action,
  which MindMesh parses robustly (fenced blocks, think tags, surrounding prose). For Ollama, use
  `format="json"` and `reasoning=False`.
- **Errors are classified.** Timeouts, HTTP 408/429/5xx and connection errors are retried with backoff. Other
  errors (auth, bad request, unknown model) fail the step at once. Usage, model name, request id and stop
  reason are recorded when the provider reports them.
- **Side effects:** a tool passed in `side_effects` is never retried after an ambiguous failure, and is never
  re-executed by safe replay.
- **Transient tool errors:** exceptions you list in `transient_errors` trigger a bounded retry. Any other
  exception is a permanent tool failure, recorded in the trace and shown to the model.
- **Registering in every process:** the agent must be registered in each process that runs, resumes, approves
  or reruns it. Put the `connect_langchain_agent` call in an `install(mm)` function, and load it with
  `MINDMESH_APPS=your_module mindmesh serve` or `mindmesh runs rerun <id> --app your_module`. Safe replay and
  inspection don't need it.

## Limits

- LangGraph graphs and prebuilt agent executors aren't wrapped; pass their model and tools instead.
- Streaming tokens, native tool-call messages and multimodal inputs aren't used; MindMesh sends text messages.
- Tools need a Pydantic `args_schema`, which `@tool` and `StructuredTool` always have.
