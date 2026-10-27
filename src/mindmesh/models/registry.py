"""Resolve model spec strings (``scripted:<brain>``, ``ollama:<model>``) to providers."""

from __future__ import annotations

from collections.abc import Callable

from .base import ModelProvider
from .ollama import OllamaProvider
from .scripted import ScriptedProvider, parse_spec


def _scripted(rest: str) -> ScriptedProvider:
    name, think_s = parse_spec(rest)
    return ScriptedProvider(name, think_s=think_s)


_FACTORIES: dict[str, Callable[[str], ModelProvider]] = {
    "scripted": _scripted,
    "ollama": lambda rest: OllamaProvider(rest or "qwen3:8b"),
}


def register_provider(prefix: str, factory: Callable[[str], ModelProvider]) -> None:
    """Plug in a new backend, e.g. ``register_provider("vllm", lambda m: VLLMProvider(m))``."""
    _FACTORIES[prefix] = factory


def resolve_model(spec: str) -> ModelProvider:
    prefix, _, rest = spec.partition(":")
    if prefix not in _FACTORIES:
        raise ValueError(f"unknown model provider {prefix!r} in {spec!r}; known: {sorted(_FACTORIES)}")
    return _FACTORIES[prefix](rest)
