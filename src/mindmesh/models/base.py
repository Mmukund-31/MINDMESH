"""Model provider protocol. Any backend that turns messages into text plugs in here."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ..core.types import ContextItem, Message, ModelResponse


@dataclass
class GenerationRequest:
    messages: list[Message]
    json_schema: dict[str, Any] | None = None
    temperature: float = 0.0
    seed: int = 0
    max_tokens: int = 1024
    # Structured view of what the model is being shown. Real LLM providers ignore it
    # (they read ``messages``); the scripted provider reasons over it deterministically.
    context: list[ContextItem] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    task: str = ""
    task_input: dict[str, Any] = field(default_factory=dict)
    tools: list[dict[str, Any]] = field(default_factory=list)
    agent: str = ""


@runtime_checkable
class ModelProvider(Protocol):
    name: str

    async def generate(self, request: GenerationRequest) -> ModelResponse: ...


def estimate_tokens(text: str) -> int:
    """Cheap, tokenizer-free estimate (~4 chars/token for English)."""
    return max(1, (len(text) + 3) // 4)
