"""Single source of time so tests and benchmarks can freeze it."""

from __future__ import annotations

from datetime import UTC, datetime

_frozen: datetime | None = None


def now() -> datetime:
    return _frozen or datetime.now(UTC)


def freeze(at: datetime | None) -> None:
    """Freeze the clock at ``at`` (``None`` unfreezes)."""
    global _frozen
    if at is not None and at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    _frozen = at


def ensure_aware(dt: datetime | None) -> datetime | None:
    """SQLite drops tz info; normalize to UTC-aware datetimes."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
