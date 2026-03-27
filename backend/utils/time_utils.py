from __future__ import annotations

from datetime import UTC, datetime


def utc_now_iso_z(*, timespec: str = "seconds") -> str:
    """
    Return an ISO-8601 UTC timestamp with a single trailing 'Z'.

    Avoids the common bug where a tz-aware isoformat() already includes '+00:00'
    and code appends another 'Z' (producing '+00:00Z').
    """
    return datetime.now(UTC).isoformat(timespec=timespec).replace("+00:00", "Z")


def iso_to_utc_z(value: datetime, *, timespec: str = "seconds") -> str:
    """Format a datetime as ISO-8601 UTC with a single trailing 'Z'."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec=timespec).replace("+00:00", "Z")

