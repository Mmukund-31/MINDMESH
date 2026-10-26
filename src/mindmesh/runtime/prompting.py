"""Prompt construction and robust parsing of model actions."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from ..core.errors import ModelOutputError
from ..core.types import AgentAction, ContextItem, FinalAnswerAction, Message, ToolCallAction
from ..policy.tools import ToolSpec

ACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": ["tool_call", "final_answer"]},
        "thought": {"type": "string"},
        "tool": {"type": "string"},
        "args": {"type": "object"},
        "answer": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["type", "thought"],
}

PROTOCOL = """\
You act by replying with exactly ONE JSON object and nothing else.
To call a tool:   {"type": "tool_call", "thought": "<why>", "tool": "<tool name>", "args": {...}}
To finish:        {"type": "final_answer", "thought": "<why>", "answer": "<answer>", "evidence": ["<context ids you relied on>"]}
Rules: only use the tools listed below; base decisions on the CONTEXT and tool results, not on assumptions;
if a tool call is blocked by policy, do not retry it unchanged; cite context ids in "evidence"."""


def build_messages(
    *,
    system_prompt: str,
    task: str,
    task_input: dict[str, Any],
    tools: list[ToolSpec],
    context: list[ContextItem],
    history: list[dict[str, Any]],
    redact: Callable[[Any], Any] = lambda x: x,
) -> list[Message]:
    """Build chat messages. ``redact`` scrubs secrets from tool I/O before it reaches the model (and the log)."""
    tool_lines = "\n".join(
        f"- {t.name}{' [side effect]' if t.side_effect else ''}: {t.description}\n  args schema: "
        f"{json.dumps(t.args_model.model_json_schema().get('properties', {}))}"
        for t in tools
    ) or "(no tools available)"
    ctx_lines = "\n".join(
        f"[{c.item_id}] ({c.kind}{', ' + c.subject_key if c.subject_key else ''}) {c.content}"
        for c in context
        if c.kind != "task"
    ) or "(empty)"
    system = f"{system_prompt}\n\n{PROTOCOL}\n\nTOOLS:\n{tool_lines}\n\nCONTEXT:\n{ctx_lines}"
    user = f"TASK: {task}"
    if task_input:
        user += f"\nINPUT: {json.dumps(task_input, default=str)}"
    msgs = [Message(role="system", content=system), Message(role="user", content=user)]
    for h in redact(history):
        msgs.append(Message(role="assistant", content=json.dumps(h["action"])))
        o = h["outcome"]
        body = {"status": o["status"]}
        if o.get("result") is not None:
            body["result"] = o["result"]
        if o.get("error"):
            body["error"] = o["error"]
        msgs.append(Message(role="tool", content=f"RESULT of {h['action'].get('tool')}: {json.dumps(body, default=str)}"))
    return msgs


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def _extract_json(text: str) -> Any:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    m = _FENCE.search(text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    raise ModelOutputError("no JSON object found in model output")


def parse_action(text: str) -> AgentAction:
    data = _extract_json(text)
    if not isinstance(data, dict):
        raise ModelOutputError("model output JSON must be an object")
    kind = data.get("type") or ("tool_call" if "tool" in data else "final_answer" if "answer" in data else None)
    try:
        if kind == "tool_call":
            return ToolCallAction.model_validate(
                {"type": "tool_call", "thought": str(data.get("thought", "")), "tool": data.get("tool"),
                 "args": data.get("args") or {}}
            )
        if kind == "final_answer":
            ev = data.get("evidence") or []
            return FinalAnswerAction.model_validate(
                {"type": "final_answer", "thought": str(data.get("thought", "")), "answer": data.get("answer"),
                 "evidence": [str(e) for e in ev] if isinstance(ev, list) else []}
            )
    except ValidationError as e:
        raise ModelOutputError(f"invalid action: {e.errors()[0]['msg']}") from None
    raise ModelOutputError(f"unknown action type {kind!r}")
