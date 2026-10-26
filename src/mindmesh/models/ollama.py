"""Ollama provider: local open-weight models (e.g. ``ollama:qwen3:8b``)."""

from __future__ import annotations

import os
import time

import httpx

from ..core.types import ModelResponse
from .base import GenerationRequest, estimate_tokens


class OllamaProvider:
    def __init__(self, model: str = "qwen3:8b", base_url: str | None = None, timeout: float = 180.0):
        self.model = model
        self.name = f"ollama:{model}"
        self.base_url = (base_url or os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434").rstrip("/")
        self.timeout = timeout

    async def generate(self, request: GenerationRequest) -> ModelResponse:
        body = {
            "model": self.model,
            "messages": [m.model_dump() for m in request.messages],
            "stream": False,
            "think": False,
            "options": {"temperature": request.temperature, "seed": request.seed, "num_predict": request.max_tokens},
        }
        if request.json_schema is not None:
            body["format"] = request.json_schema
        t0 = time.perf_counter()
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(f"{self.base_url}/api/chat", json=body)
            r.raise_for_status()
            data = r.json()
        text = data.get("message", {}).get("content", "")
        prompt = "".join(m.content for m in request.messages)
        return ModelResponse(
            text=text,
            model=self.name,
            tokens_in=data.get("prompt_eval_count") or estimate_tokens(prompt),
            tokens_out=data.get("eval_count") or estimate_tokens(text),
            latency_ms=(time.perf_counter() - t0) * 1000,
        )
