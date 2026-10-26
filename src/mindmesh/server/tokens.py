"""Short-lived HMAC-signed stream tokens, so browsers never put API keys in URLs."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _sign(secret: str, body: str) -> str:
    return _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())


def issue_stream_token(secret: str, project_id: str, run_id: str, ttl_s: int, *, now: float | None = None) -> str:
    exp = int((now if now is not None else time.time()) + ttl_s)
    body = _b64(json.dumps({"p": project_id, "r": run_id, "exp": exp}, separators=(",", ":")).encode())
    return f"{body}.{_sign(secret, body)}"


def verify_stream_token(secret: str, token: str, run_id: str, *, now: float | None = None) -> str | None:
    """Return the token's project id if it is authentic, unexpired and bound to ``run_id``."""
    try:
        body, sig = token.split(".", 1)
        if not hmac.compare_digest(sig, _sign(secret, body)):
            return None
        claims = json.loads(_unb64(body))
    except (ValueError, TypeError):
        return None
    if claims.get("r") != run_id or int(claims.get("exp", 0)) < (now if now is not None else time.time()):
        return None
    return claims.get("p") or None
