"""Embedding backends. ``HashingEmbedder`` is offline and deterministic; ``OllamaEmbedder`` runs a local model."""

from __future__ import annotations

import hashlib
import math
import os
import re
from typing import Protocol, runtime_checkable

import httpx

_WORD = re.compile(r"[a-z0-9]+")
_STOP = {
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is", "are", "be", "was", "were", "it",
    "this", "that", "with", "as", "at", "by", "from", "can", "will", "should", "do", "does", "i", "we", "you",
}


def tokenize(text: str) -> list[str]:
    return [_stem(w) for w in _WORD.findall(text.lower()) if w not in _STOP]


def _stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            return w[: -len(suf)]
    return w


@runtime_checkable
class Embedder(Protocol):
    name: str
    dim: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashingEmbedder:
    """Feature-hashed bag of words + word bigrams + char trigrams, L2-normalised."""

    def __init__(self, dim: int = 384):
        self.dim = dim
        self.name = f"hashing-{dim}"

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        toks = tokenize(text)
        feats: list[tuple[str, float]] = [(t, 1.0) for t in toks]
        feats += [(f"{a}_{b}", 0.7) for a, b in zip(toks, toks[1:], strict=False)]
        for t in toks:
            padded = f"#{t}#"
            feats += [(padded[i : i + 3], 0.25) for i in range(len(padded) - 2)]
        for f, w in feats:
            h = int.from_bytes(hashlib.blake2b(f.encode(), digest_size=8).digest(), "big")
            v[h % self.dim] += w if (h >> 63) & 1 else -w
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]


class OllamaEmbedder:
    def __init__(self, model: str = "nomic-embed-text", base_url: str | None = None, dim: int = 768):
        self.model = model
        self.dim = dim
        self.name = f"ollama:{model}"
        self.base_url = (base_url or os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434").rstrip("/")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(f"{self.base_url}/api/embed", json={"model": self.model, "input": texts})
            r.raise_for_status()
            return r.json()["embeddings"]


def resolve_embedder(spec: str) -> Embedder:
    prefix, _, rest = spec.partition(":")
    if prefix == "hashing":
        return HashingEmbedder(int(rest) if rest else 384)
    if prefix == "ollama":
        return OllamaEmbedder(rest or "nomic-embed-text")
    raise ValueError(f"unknown embedder {spec!r}")
