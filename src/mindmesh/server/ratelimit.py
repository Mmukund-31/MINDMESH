"""ASGI middleware: per-client token-bucket rate limiting (in-process; one bucket set per server instance)."""

from __future__ import annotations

import json
import math
import time

from starlette.types import ASGIApp, Receive, Scope, Send

from .security import SECURITY_HEADERS

EXEMPT_PATHS = ("/healthz",)
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
MAX_CLIENTS = 50_000


class _Bucket:
    __slots__ = ("tokens", "updated")

    def __init__(self, capacity: float, now: float):
        self.tokens, self.updated = capacity, now

    def take(self, capacity: float, per_s: float, now: float) -> float:
        """Take one token; return 0 on success, else the seconds until one is available."""
        self.tokens = min(capacity, self.tokens + (now - self.updated) * per_s)
        self.updated = now
        if self.tokens >= 1:
            self.tokens -= 1
            return 0.0
        return (1 - self.tokens) / per_s


class RateLimitMiddleware:
    """``per_minute`` requests per client IP, and ``writes_per_minute`` of those for non-GET methods.

    The client is ``scope["client"]``, or, behind an edge proxy that sets it, the ``client_ip_header`` value (e.g.
    ``true-client-ip``): unlike the leftmost ``X-Forwarded-For`` entry, callers cannot forge it. A limit of 0
    disables that bucket."""

    def __init__(self, app: ASGIApp, *, per_minute: int, writes_per_minute: int,
                 client_ip_header: str | None = None, clock=time.monotonic):
        self.app = app
        self.client_ip_header = client_ip_header.lower().encode() if client_ip_header else None
        self.limits = {"all": per_minute, "write": writes_per_minute}
        self.clock = clock
        self._buckets: dict[tuple[str, str], _Bucket] = {}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in EXEMPT_PATHS or scope["method"] == "OPTIONS":
            await self.app(scope, receive, send)
            return
        client = self._client(scope)
        kinds = ["all"] if scope["method"] in SAFE_METHODS else ["all", "write"]
        now = self.clock()
        for kind in kinds:
            limit = self.limits[kind]
            if not limit:
                continue
            wait = self._bucket(client, kind, limit, now).take(limit, limit / 60.0, now)
            if wait:
                await self._reject(send, kind, limit, wait)
                return
        await self.app(scope, receive, send)

    def _client(self, scope: Scope) -> str:
        if self.client_ip_header:
            for name, value in scope.get("headers", []):
                if name == self.client_ip_header and value:
                    return value.decode("latin-1").split(",")[0].strip()
        return (scope.get("client") or ("unknown", 0))[0]

    def _bucket(self, client: str, kind: str, capacity: int, now: float) -> _Bucket:
        key = (client, kind)
        bucket = self._buckets.get(key)
        if bucket is None:
            if len(self._buckets) >= MAX_CLIENTS:
                self._buckets.clear()
            bucket = self._buckets[key] = _Bucket(capacity, now)
        return bucket

    async def _reject(self, send: Send, kind: str, limit: int, wait: float) -> None:
        what = "write requests" if kind == "write" else "requests"
        body = json.dumps({"detail": f"rate limit exceeded: {limit} {what} per minute; retry later"}).encode()
        await send({"type": "http.response.start", "status": 429,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode()),
                                (b"retry-after", str(max(1, math.ceil(wait))).encode()), *SECURITY_HEADERS]})
        await send({"type": "http.response.body", "body": body})
