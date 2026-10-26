"""Secret redaction applied to every payload before it is persisted or streamed."""

from __future__ import annotations

import re
from typing import Any

MASK = "***REDACTED***"

DEFAULT_SENSITIVE_KEYS = {
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "access_token",
    "refresh_token",
    "private_key",
    "client_secret",
    "ssn",
    "card_number",
}

DEFAULT_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),  # OpenAI-style keys
    re.compile(r"\bmm_[A-Za-z0-9_-]{16,}"),  # MindMesh API keys
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),  # AWS access key id
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),  # GitHub tokens
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:\d[ -]?){13,16}\b"),  # payment card numbers
]


class Redactor:
    def __init__(self, extra_keys: set[str] | None = None, extra_patterns: list[str] | None = None):
        self.keys = {k.lower() for k in DEFAULT_SENSITIVE_KEYS | (extra_keys or set())}
        self.patterns = DEFAULT_PATTERNS + [re.compile(p) for p in (extra_patterns or [])]
        # key/value pairs embedded in free text or serialized JSON, e.g. '"password": "x"' or 'token=x'
        keys = "|".join(sorted((re.escape(k) for k in self.keys), key=len, reverse=True))
        self.kv = re.compile(rf'(?i)(["\']?\b(?:{keys})\b["\']?\s*[:=]\s*)("(?:[^"\\]|\\.)*"|\'[^\']*\'|[^\s,;}}]+)')

    def text(self, s: str) -> str:
        s = self.kv.sub(lambda m: f'{m.group(1)}"{MASK}"', s)
        for p in self.patterns:
            s = p.sub(MASK, s)
        return s

    def __call__(self, value: Any, _depth: int = 0) -> Any:
        if _depth > 25:
            return "<max depth>"
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            out = {}
            for k, v in value.items():
                if isinstance(k, str) and k.lower() in self.keys and v not in (None, ""):
                    out[k] = MASK
                else:
                    out[k] = self(v, _depth + 1)
            return out
        if isinstance(value, list | tuple):
            return [self(v, _depth + 1) for v in value]
        return value


default_redactor = Redactor()
