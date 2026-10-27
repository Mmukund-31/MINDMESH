"""Event-loop selection.

psycopg's async driver cannot run on Windows' default ``ProactorEventLoop``, so on Windows every entry point
(CLI, server, migrations, tests) uses a ``SelectorEventLoop``. Elsewhere the platform default is kept.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable, Coroutine
from typing import Any

NEEDS_SELECTOR_LOOP = sys.platform == "win32"


def new_event_loop() -> asyncio.AbstractEventLoop:
    """A loop that every supported database driver can use. Also a uvicorn ``--loop`` factory."""
    return asyncio.SelectorEventLoop() if NEEDS_SELECTOR_LOOP else asyncio.new_event_loop()


def run[T](coro: Coroutine[Any, Any, T]) -> T:
    """``asyncio.run`` with a driver-compatible loop. Use this instead of ``asyncio.run`` for scripts that
    talk to PostgreSQL."""
    factory: Callable[[], asyncio.AbstractEventLoop] | None = new_event_loop if NEEDS_SELECTOR_LOOP else None
    return asyncio.run(coro, loop_factory=factory)


def uvicorn_loop() -> str:
    return "mindmesh.core.aio:new_event_loop" if NEEDS_SELECTOR_LOOP else "auto"
