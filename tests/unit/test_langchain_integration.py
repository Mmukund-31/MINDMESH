"""LangChain integration: LangChain chat models and tools run under MindMesh's runtime (policies, approvals,
validation, retries, tracing, replay) without changes to the runtime."""

import json

import pytest

pytest.importorskip("langchain_core")

from langchain_core.language_models.fake_chat_models import FakeListChatModel  # noqa: E402
from langchain_core.tools import tool  # noqa: E402

from mindmesh import Condition, PolicyRuleIn  # noqa: E402
from mindmesh.core.errors import ModelProviderError  # noqa: E402
from mindmesh.integrations.langchain import (  # noqa: E402
    LangChainProvider,
    add_langchain_tool,
    connect_langchain_agent,
)
from mindmesh.models.base import GenerationRequest  # noqa: E402

PAID: list[dict] = []


@tool
def lookup_invoice(invoice_id: str) -> dict:
    """Look up an invoice by id."""
    return {"invoice_id": invoice_id, "vendor": "ACME", "amount": 1500.0}


@tool
def pay_invoice(invoice_id: str, amount: float) -> str:
    """Pay an invoice."""
    PAID.append({"invoice_id": invoice_id, "amount": amount})
    return f"paid {invoice_id}"


def call(tool_name: str, **args) -> str:
    return json.dumps({"type": "tool_call", "thought": f"use {tool_name}", "tool": tool_name, "args": args})


def answer(text: str) -> str:
    return json.dumps({"type": "final_answer", "thought": "done", "answer": text})


@pytest.fixture(autouse=True)
def _reset():
    PAID.clear()


def connect(mm, responses):
    return connect_langchain_agent(mm, "payables", FakeListChatModel(responses=responses),
                                   tools=[lookup_invoice, pay_invoice], side_effects=["pay_invoice"],
                                   system_prompt="You pay vendor invoices.")


async def test_langchain_agent_runs_and_is_traced(mm):
    spec = connect(mm, [call("lookup_invoice", invoice_id="INV-7"), call("pay_invoice", invoice_id="INV-7",
                   amount=1500.0), answer("INV-7 paid")])
    assert spec.model == "langchain:payables" and mm.tools.get("pay_invoice").side_effect
    run = await mm.run("payables", "Pay invoice INV-7")
    assert run.status == "succeeded" and run.result["answer"] == "INV-7 paid"
    assert PAID == [{"invoice_id": "INV-7", "amount": 1500.0}]
    steps = [e.payload["action"].get("tool") for e in await mm.repos.events.list(run.id, types=["step.finished"])]
    assert steps == ["lookup_invoice", "pay_invoice", None]
    model_calls = await mm.repos.events.list(run.id, types=["model.called"])
    assert model_calls and model_calls[0].payload["model"] == "langchain:payables"


async def test_policies_and_approvals_gate_langchain_tools(mm):
    await mm.add_policy(PolicyRuleIn(name="approve-large", effect="require_approval", tools=["pay_invoice"],
                                     conditions=[Condition(arg="amount", op="gt", value=1000)]))
    connect(mm, [call("pay_invoice", invoice_id="INV-7", amount=1500.0), answer("paid after approval")])
    run = await mm.run("payables", "Pay invoice INV-7")
    assert run.status == "waiting_approval" and PAID == []  # nothing executed before a human decided
    [appr] = await mm.repos.approvals.list(status="pending", run_id=run.id)
    _, run = await mm.resolve_approval(appr.id, approve=True, resolver="cfo")
    assert run.status == "succeeded" and PAID == [{"invoice_id": "INV-7", "amount": 1500.0}]


async def test_langchain_tool_arguments_are_validated_strictly(mm):
    spec = add_langchain_tool(mm, pay_invoice, side_effect=True)
    assert spec.validate({"invoice_id": "INV-1", "amount": 10}) == {"invoice_id": "INV-1", "amount": 10.0}
    from mindmesh.core.errors import ToolArgumentError

    with pytest.raises(ToolArgumentError, match="Extra inputs"):
        spec.validate({"invoice_id": "INV-1", "amount": 10, "note": "sneaky"})
    with pytest.raises(ToolArgumentError, match="amount"):
        spec.validate({"invoice_id": "INV-1"})


async def test_transient_tool_errors_are_retried(mm):
    attempts = []

    @tool
    def flaky_search(query: str) -> str:
        """Search that fails once."""
        attempts.append(query)
        if len(attempts) == 1:
            raise ConnectionError("upstream reset")
        return "3 results"

    add_langchain_tool(mm, flaky_search, transient_errors=(ConnectionError,))
    connect_langchain_agent(mm, "searcher", FakeListChatModel(responses=[call("flaky_search", query="x"),
                                                                         answer("found 3")]),
                            tools=[], system_prompt="search")
    mm.agents["searcher"] = mm.agents["searcher"].model_copy(update={"tools": ["flaky_search"]})
    run = await mm.run("searcher", "search x")
    assert run.status == "succeeded" and len(attempts) == 2


async def test_safe_replay_of_a_langchain_run_executes_nothing(mm):
    connect(mm, [call("pay_invoice", invoice_id="INV-9", amount=20.0), answer("paid")])
    run = await mm.run("payables", "Pay INV-9")
    assert PAID == [{"invoice_id": "INV-9", "amount": 20.0}]
    replay = await mm.replay(run.id)
    assert replay.status == "succeeded" and replay.result["answer"] == "paid"
    assert len(PAID) == 1  # recorded outputs were used: no second payment, no model call


class _RateLimited(Exception):
    status_code = 429


class _BadRequest(Exception):
    status_code = 400


class _Boom:
    def __init__(self, exc):
        self.exc, self.model_name = exc, "boom-1"

    async def ainvoke(self, messages):
        raise self.exc


@pytest.mark.parametrize("exc, retryable", [(_RateLimited("slow down"), True), (TimeoutError(), True),
                                            (_BadRequest("bad"), False), (ValueError("nope"), False)])
async def test_provider_errors_are_classified(exc, retryable):
    p = LangChainProvider(_Boom(exc))
    with pytest.raises(ModelProviderError) as e:
        await p.generate(GenerationRequest(messages=[]))
    assert e.value.retryable is retryable and p.name == "langchain:boom-1"


async def test_side_effects_must_name_passed_tools(mm):
    with pytest.raises(ValueError, match="pay_everything"):
        connect_langchain_agent(mm, "x", FakeListChatModel(responses=[]), tools=[lookup_invoice],
                                side_effects=["pay_everything"])
