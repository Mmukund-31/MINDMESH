"""Ollama provider: local open-weight models (e.g. ``ollama:qwen3:4b``).

Everything recorded about a call comes from the server's response where Ollama reports it:
the model name it actually ran, the weights digest (from ``/api/tags``), prompt/completion
token counts and its own timing breakdown. Failures are classified so the runtime only
retries faults that can succeed on a second attempt.
"""

from __future__ import annotations

import os
import time

import httpx

from ..core.errors import ModelProviderError
from ..core.types import ModelResponse
from .base import GenerationRequest, estimate_tokens

_TIMINGS = {"total_duration": "total", "load_duration": "load", "prompt_eval_duration": "prompt_eval",
            "eval_duration": "eval"}


class OllamaProvider:
    def __init__(
        self,
        model: str = "qwen3:8b",
        base_url: str | None = None,
        timeout: float = 180.0,
        *,
        structured: bool = True,
        keep_alive: str = "10m",
    ):
        self.model = model
        self.name = f"ollama:{model}"
        self.base_url = (base_url or os.environ.get("OLLAMA_BASE_URL") or "http://127.0.0.1:11434").rstrip("/")
        self.timeout = timeout
        # structured=False sends no JSON schema, so the reply is free text and exercises the output parser.
        self.structured = structured
        self.keep_alive = keep_alive
        self._digest: str | None = None

    async def _model_digest(self, client: httpx.AsyncClient) -> str | None:
        if self._digest is None:
            try:
                r = await client.get(f"{self.base_url}/api/tags")
                r.raise_for_status()
                for m in r.json().get("models", []):
                    if self.model in (m.get("name"), m.get("model")):
                        self._digest = m.get("digest")
                        break
            except httpx.HTTPError:
                return None  # metadata only; never fail a generation over it
        return self._digest

    async def generate(self, request: GenerationRequest) -> ModelResponse:
        body = {
            "model": self.model,
            "messages": [m.model_dump() for m in request.messages],
            "stream": False,
            "think": False,
            "keep_alive": self.keep_alive,
            "options": {"temperature": request.temperature, "seed": request.seed, "num_predict": request.max_tokens},
        }
        if request.json_schema is not None and self.structured:
            body["format"] = request.json_schema
        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(f"{self.base_url}/api/chat", json=body)
                if r.status_code >= 400:
                    raise _http_error(r)
                data = r.json()
                digest = await self._model_digest(client)
        except httpx.TimeoutException as e:
            raise ModelProviderError(f"ollama timed out: {type(e).__name__}", retryable=True, kind="timeout") from e
        except httpx.TransportError as e:
            raise ModelProviderError(f"ollama unreachable at {self.base_url}: {type(e).__name__}: {e}",
                                     retryable=True, kind="connection") from e
        except ValueError as e:  # undecodable body
            raise ModelProviderError(f"ollama returned invalid JSON: {e}", retryable=True) from e
        if data.get("error"):
            raise ModelProviderError(f"ollama error: {data['error']}", retryable=False)
        text = data.get("message", {}).get("content", "")
        prompt_n, out_n = data.get("prompt_eval_count"), data.get("eval_count")
        return ModelResponse(
            text=text,
            model=self.name,
            tokens_in=prompt_n if prompt_n is not None else estimate_tokens("".join(m.content for m in request.messages)),
            tokens_out=out_n if out_n is not None else estimate_tokens(text),
            latency_ms=(time.perf_counter() - t0) * 1000,
            model_reported=data.get("model"),
            model_digest=digest,
            stop_reason=data.get("done_reason"),
            usage_reported=prompt_n is not None and out_n is not None,
            provider_timing_ms={v: data[k] / 1e6 for k, v in _TIMINGS.items() if isinstance(data.get(k), int | float)},
        )


def _http_error(r: httpx.Response) -> ModelProviderError:
    try:
        detail = r.json().get("error") or r.text
    except ValueError:
        detail = r.text
    # 408/429/5xx can succeed later; 4xx (unknown model, bad request) never will.
    retryable = r.status_code in (408, 429) or r.status_code >= 500
    return ModelProviderError(f"ollama HTTP {r.status_code}: {str(detail)[:300]}", retryable=retryable,
                              status=r.status_code)
