"""ASGI middleware: request body size limit and baseline security headers."""

from __future__ import annotations

import json

from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
]


class _TooLarge(HTTPException):
    """Raised from ``receive`` for chunked bodies; an HTTPException so FastAPI answers 413, not 400."""

    def __init__(self, limit: int):
        super().__init__(413, f"request body exceeds {limit} bytes")


class SecurityMiddleware:
    def __init__(self, app: ASGIApp, *, max_body_bytes: int):
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    too_large = int(value) > self.max_body_bytes
                except ValueError:
                    too_large = True
                if too_large:
                    await self._reject(send)
                    return

        received = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    raise _TooLarge(self.max_body_bytes)
            return message

        async def send_with_headers(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                headers += [(k, v) for k, v in SECURITY_HEADERS if k not in present]
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, limited_receive, send_with_headers)
        except _TooLarge:
            if not started:
                await self._reject(send)

    async def _reject(self, send: Send) -> None:
        body = json.dumps({"detail": f"request body exceeds {self.max_body_bytes} bytes"}).encode()
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode()), *SECURITY_HEADERS]})
        await send({"type": "http.response.body", "body": body})
