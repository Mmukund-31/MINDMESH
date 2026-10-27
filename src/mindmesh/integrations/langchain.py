"""LangChain integration: run a LangChain agent's model and tools under MindMesh.

MindMesh drives the agent loop itself, so every tool call passes argument validation, policy enforcement and
human approval *before* it executes, and every step is traced, replayable and comparable. LangChain supplies
the parts it is good at: chat-model clients for every provider and a large tool ecosystem.

    from langchain_ollama import ChatOllama
    from langchain_core.tools import tool
    from mindmesh.integrations.langchain import connect_langchain_agent

    @tool
    def get_weather(city: str) -> str:
        "Current weather for a city."
        ...

    connect_langchain_agent(mm, "weather", ChatOllama(model="qwen3:4b", reasoning=False),
                            tools=[get_weather], system_prompt="You answer weather questions.")
    run = await mm.run("weather", "Do I need an umbrella in Pune?")

Requires ``pip install "mindmesh[langchain]"`` (``langchain-core``) plus the provider package you use
(``langchain-ollama``, ``langchain-openai``, ``langchain-anthropic``, ...).
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict

from ..core.errors import ModelProviderError, TransientToolError
from ..core.types import AgentSpec, Message, ModelResponse
from ..models.base import GenerationRequest, estimate_tokens
from ..policy.tools import ToolSpec

if TYPE_CHECKING:  # pragma: no cover
    from langchain_core.language_models import BaseChatModel
    from langchain_core.tools import BaseTool

    from ..sdk import MindMesh

_TRANSIENT_NAMES = ("timeout", "ratelimit", "connection", "unavailable", "overloaded")


def _require_langchain() -> None:
    try:
        import langchain_core  # noqa: F401
    except ImportError as e:  # pragma: no cover - exercised only without the extra
        raise ImportError('the LangChain integration needs langchain-core: pip install "mindmesh[langchain]"') from e


# ---------------------------------------------------------------------------------------------- models


def _to_langchain(m: Message):
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    if m.role == "system":
        return SystemMessage(m.content)
    if m.role == "assistant":
        return AIMessage(m.content)
    # MindMesh's tool results are plain text turns (the action protocol is JSON, not native tool calling),
    # so they map to user turns; LangChain's ToolMessage would require provider-side tool-call ids.
    return HumanMessage(m.content)


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # content blocks: keep the text ones
        return "".join(b if isinstance(b, str) else b.get("text", "") for b in content
                       if isinstance(b, str) or b.get("type") == "text")
    return str(content)


def _model_name(chat_model: Any) -> str:
    for attr in ("model_name", "model", "model_id"):
        v = getattr(chat_model, attr, None)
        if isinstance(v, str) and v:
            return v
    return type(chat_model).__name__


def _is_transient(exc: BaseException) -> bool:
    status = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
    if isinstance(status, int):
        return status in (408, 429) or status >= 500
    if isinstance(exc, TimeoutError | ConnectionError):
        return True
    name = type(exc).__name__.lower()
    return any(t in name for t in _TRANSIENT_NAMES)


class LangChainProvider:
    """A MindMesh :class:`~mindmesh.models.base.ModelProvider` backed by any LangChain chat model.

    The model receives MindMesh's prompt (tools, assembled context, JSON action protocol) and replies with one
    JSON action; MindMesh parses it, so models without native tool calling work too. Errors are classified as
    retryable (timeouts, rate limits, 5xx, connection) or permanent, like the built-in providers."""

    def __init__(self, chat_model: BaseChatModel, name: str | None = None):
        _require_langchain()
        self.chat_model = chat_model
        self.name = name or f"langchain:{_model_name(chat_model)}"

    async def generate(self, request: GenerationRequest) -> ModelResponse:
        messages = [_to_langchain(m) for m in request.messages]
        t0 = time.perf_counter()
        try:
            ai = await self.chat_model.ainvoke(messages)
        except Exception as e:  # noqa: BLE001 - any client error becomes a classified provider error
            kind = "timeout" if "timeout" in type(e).__name__.lower() or isinstance(e, TimeoutError) else "provider"
            raise ModelProviderError(f"{self.name}: {type(e).__name__}: {e}"[:400], retryable=_is_transient(e),
                                     status=getattr(e, "status_code", None), kind=kind) from e
        text = _text(ai.content)
        usage = getattr(ai, "usage_metadata", None) or {}
        meta = getattr(ai, "response_metadata", None) or {}
        return ModelResponse(
            text=text,
            model=self.name,
            tokens_in=usage.get("input_tokens") or estimate_tokens("".join(m.content for m in request.messages)),
            tokens_out=usage.get("output_tokens") or estimate_tokens(text),
            latency_ms=(time.perf_counter() - t0) * 1000,
            model_reported=meta.get("model_name") or meta.get("model"),
            request_id=getattr(ai, "id", None),
            stop_reason=meta.get("finish_reason") or meta.get("done_reason") or meta.get("stop_reason"),
            usage_reported=bool(usage),
        )


# ----------------------------------------------------------------------------------------------- tools


def _strict(schema: type[BaseModel], name: str) -> type[BaseModel]:
    """The tool's own argument model, tightened like native MindMesh tools: unknown fields are rejected."""
    return type(f"{name.replace('.', '_')}_args", (schema,), {"model_config": ConfigDict(extra="forbid")})


def add_langchain_tool(
    mm: MindMesh,
    lc_tool: BaseTool,
    *,
    name: str | None = None,
    side_effect: bool = False,
    timeout_s: float | None = None,
    transient_errors: tuple[type[BaseException], ...] = (),
    tags: Iterable[str] = (),
) -> ToolSpec:
    """Register a LangChain tool as a MindMesh tool.

    Mark tools that change the world with ``side_effect=True``: they are never retried after an ambiguous
    failure and are skipped during safe replay. Exceptions listed in ``transient_errors`` become
    :class:`~mindmesh.TransientToolError` (bounded retry); any other exception is a permanent failure."""
    _require_langchain()
    schema = getattr(lc_tool, "tool_call_schema", None) or lc_tool.args_schema
    if not (isinstance(schema, type) and issubclass(schema, BaseModel)):
        raise TypeError(f"LangChain tool {lc_tool.name!r} has no Pydantic args schema; define it with @tool or "
                        "args_schema=<BaseModel>")
    tool_name = name or lc_tool.name

    async def invoke(**kwargs: Any) -> Any:
        try:
            return await lc_tool.ainvoke(kwargs)
        except transient_errors as e:
            raise TransientToolError(f"{tool_name}: {type(e).__name__}: {e}") from e

    return mm.tools.add(ToolSpec(
        name=tool_name,
        fn=invoke,
        args_model=_strict(schema, tool_name),
        description=lc_tool.description or "",
        side_effect=side_effect,
        timeout_s=timeout_s,
        wants_ctx=False,
        tags=["langchain", *tags],
    ))


# ----------------------------------------------------------------------------------------------- agents


def connect_langchain_agent(
    mm: MindMesh,
    name: str,
    chat_model: BaseChatModel,
    tools: Iterable[BaseTool] = (),
    *,
    system_prompt: str = "",
    side_effects: Iterable[str] = (),
    **agent_fields: Any,
) -> AgentSpec:
    """Register a LangChain model + tools as a MindMesh agent and return its :class:`~mindmesh.AgentSpec`.

    ``side_effects`` names the tools that change the world. Further ``AgentSpec`` fields (``limits``,
    ``context``, ``memory_scopes``, ``claim_checks``, ...) pass through. The model is pinned under the spec
    ``langchain:<agent name>``; register the agent in every process that runs, resumes or reruns it (for the
    API server, list your module in ``MINDMESH_APPS``)."""
    side = set(side_effects)
    tools = list(tools)
    unknown = side - {t.name for t in tools}
    if unknown:
        raise ValueError(f"side_effects names tools that were not passed: {sorted(unknown)}")
    for t in tools:
        add_langchain_tool(mm, t, side_effect=t.name in side)
    model_spec = f"langchain:{name}"
    mm.register_provider_instance(model_spec, LangChainProvider(chat_model, name=model_spec))
    fields = {**({"system_prompt": system_prompt} if system_prompt else {}), **agent_fields}
    return mm.agent(AgentSpec(name=name, tools=[t.name for t in tools], model=model_spec, **fields))
