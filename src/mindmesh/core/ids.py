"""Sortable, prefixed identifiers (time-ordered, URL safe)."""

from __future__ import annotations

import os
import time

_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"  # Crockford base32 (lowercase)


def _b32(n: int, width: int) -> str:
    out = []
    for _ in range(width):
        out.append(_ALPHABET[n & 31])
        n >>= 5
    return "".join(reversed(out))


def new_id(prefix: str) -> str:
    """Return ``<prefix>_<10 chars time><12 chars random>``; ids sort by creation time."""
    ts = int(time.time() * 1000)
    rnd = int.from_bytes(os.urandom(8), "big")
    return f"{prefix}_{_b32(ts, 10)}{_b32(rnd, 12)}"
