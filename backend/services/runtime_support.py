"""Shared runtime helpers for the FastAPI app and background workers."""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from typing import Any, Callable
from uuid import uuid4

import httpx

from utils.request_context import record_db_roundtrip

logger = logging.getLogger("ev_tracker")
BOOT_ID = uuid4().hex[:12]


def app_role() -> str:
    """Return normalized runtime role used by entrypoint orchestration."""
    import os

    role = (os.getenv("APP_ROLE") or "api").strip().lower()
    return "scheduler" if role == "scheduler" else "api"


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def new_run_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def log_event(event: str, level: str = "info", **fields: Any) -> None:
    payload = {
        "event": event,
        "timestamp": utc_now_iso(),
        **fields,
    }
    message = json.dumps(payload, default=str)
    getattr(logger, level.lower(), logger.info)(message)


def retry_supabase(
    f: Callable[[], Any],
    retries: int = 2,
    *,
    label: str = "supabase.request",
    slow_ms: float = 250.0,
) -> Any:
    """Retry a Supabase/PostgREST request on transient transport errors."""
    last_err = None
    retryable_errors = (
        httpx.RemoteProtocolError,
        httpx.ReadError,
        httpx.ConnectError,
        httpx.PoolTimeout,
        httpx.TimeoutException,
    )
    for attempt in range(retries):
        started_at = time.monotonic()
        try:
            result = f()
            duration_ms = round((time.monotonic() - started_at) * 1000, 2)
            record_db_roundtrip(duration_ms)
            if attempt > 0 or duration_ms >= slow_ms:
                log_event(
                    "supabase.request.completed",
                    label=label,
                    duration_ms=duration_ms,
                    attempt=attempt + 1,
                    retries=retries,
                )
            return result
        except retryable_errors as exc:
            last_err = exc
            duration_ms = round((time.monotonic() - started_at) * 1000, 2)
            record_db_roundtrip(duration_ms)
            if attempt == retries - 1:
                log_event(
                    "supabase.request.failed",
                    level="warning",
                    label=label,
                    duration_ms=duration_ms,
                    attempt=attempt + 1,
                    retries=retries,
                    error_class=type(exc).__name__,
                    error=str(exc),
                )
                raise
            delay_seconds = min(0.35, 0.1 * (2**attempt))
            log_event(
                "supabase.request.retrying",
                level="warning",
                label=label,
                duration_ms=duration_ms,
                attempt=attempt + 1,
                retries=retries,
                retry_delay_ms=round(delay_seconds * 1000, 2),
                error_class=type(exc).__name__,
                error=str(exc),
            )
            time.sleep(delay_seconds)
    if last_err:
        raise last_err
