"""Deterministic, offline model provider.

A *brain* is a plain function ``(GenerationRequest) -> dict | str`` that decides
the next action **only from what the request exposes** (context items, prior
tool results, task). This keeps benchmarks reproducible while still exercising
the full runtime: if the context engine drops the evidence, the brain cannot
see it and fails exactly like a real model would.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from typing import Any

from ..core.errors import ModelProviderError
from ..core.types import ModelResponse
from .base import GenerationRequest, estimate_tokens

Brain = Callable[[GenerationRequest], "dict[str, Any] | str"]

_BRAINS: dict[str, Brain] = {}


def brain(name: str) -> Callable[[Brain], Brain]:
    """Register a scripted brain under ``scripted:<name>``."""

    def deco(fn: Brain) -> Brain:
        _BRAINS[name] = fn
        return fn

    return deco


def get_brain(name: str) -> Brain:
    if name not in _BRAINS:
        raise KeyError(f"unknown scripted brain {name!r}; registered: {sorted(_BRAINS)}")
    return _BRAINS[name]


@brain("echo")
def _echo(req: GenerationRequest) -> dict[str, Any]:
    return {"type": "final_answer", "answer": f"echo: {req.task}"}


MAX_THINK_MS = 5000


def parse_spec(rest: str) -> tuple[str, float]:
    """``refund-support?think_ms=700`` -> (brain, seconds of simulated thinking time per call)."""
    name, _, query = rest.partition("?")
    think_ms = 0.0
    for part in filter(None, query.split("&")):
        key, _, value = part.partition("=")
        if key != "think_ms":
            raise ValueError(f"unknown scripted model option {key!r} (supported: think_ms)")
        think_ms = float(value)
        if not 0 <= think_ms <= MAX_THINK_MS:
            raise ValueError(f"think_ms must be between 0 and {MAX_THINK_MS}")
    return name or "echo", think_ms / 1000


class ScriptedProvider:
    """``think_s`` paces demos: the run streams at human speed instead of finishing in milliseconds."""

    def __init__(self, brain_name: str = "echo", fn: Brain | None = None, think_s: float = 0.0):
        self.name = f"scripted:{brain_name}"
        self._fn = fn or get_brain(brain_name)
        self.think_s = think_s

    async def generate(self, request: GenerationRequest) -> ModelResponse:
        t0 = time.perf_counter()
        if self.think_s:
            await asyncio.sleep(self.think_s)
        out = self._fn(request)
        text = out if isinstance(out, str) else json.dumps(out)
        prompt = "".join(m.content for m in request.messages)
        return ModelResponse(
            text=text,
            model=self.name,
            tokens_in=estimate_tokens(prompt),
            tokens_out=estimate_tokens(text),
            latency_ms=(time.perf_counter() - t0) * 1000,
        )


class RecordedProvider:
    """Replays model outputs captured in a previous run (safe replay).

    Given a list, responses are served in order. Given a ``{step: [responses]}`` mapping, each step is
    served its own recorded attempts, so replay stays aligned even when the original run redid a step.
    Running out is a permanent error: the replay has diverged and must not be retried.
    """

    def __init__(self, responses: list[ModelResponse] | dict[int, list[ModelResponse]], name: str = "recorded"):
        self.name = name
        self._by_step = {k: list(v) for k, v in responses.items()} if isinstance(responses, dict) else None
        self._responses = [] if isinstance(responses, dict) else list(responses)
        self._i = 0
        self._served: dict[int, int] = {}

    async def generate(self, request: GenerationRequest) -> ModelResponse:
        if self._by_step is not None:
            pool, i = self._by_step.get(request.step, []), self._served.get(request.step, 0)
            self._served[request.step] = i + 1
        else:
            pool, i = self._responses, self._i
            self._i += 1
        if i >= len(pool):
            raise ModelProviderError(
                f"recorded model responses exhausted at step {request.step}: execution diverged from the "
                "original run", retryable=False, kind="replay_diverged",
            )
        return pool[i]
