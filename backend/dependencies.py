import os
import time

from fastapi import Depends, Header, HTTPException

from auth import admin_allowlist, get_current_user, is_admin_email
from database import get_db
from services.analytics_events import capture_backend_event
from services.shared_state import allow_fixed_window_rate_limit

SCAN_RATE_WINDOW_SECONDS = 15 * 60
SCAN_RATE_MAX_REQUESTS = 12


def get_db_dependency():
    return get_db()


async def require_current_user(user: dict = Depends(get_current_user)) -> dict:
    return user


async def require_admin_user(user: dict = Depends(get_current_user)) -> dict:
    if not admin_allowlist():
        raise HTTPException(status_code=503, detail="OPS_ADMIN_EMAILS not configured")

    if not is_admin_email(user.get("email")):
        raise HTTPException(status_code=403, detail="Forbidden")

    return user


async def require_scan_rate_limit(
    user: dict = Depends(get_current_user),
    x_session_id: str | None = Header(default=None, alias="X-Session-ID"),
) -> dict:
    """Allow at most SCAN_RATE_MAX_REQUESTS scan requests per user per SCAN_RATE_WINDOW_SECONDS."""
    uid = user["id"]
    allowed = allow_fixed_window_rate_limit(
        bucket_key=f"scan:{uid}",
        max_requests=SCAN_RATE_MAX_REQUESTS,
        window_seconds=SCAN_RATE_WINDOW_SECONDS,
    )
    if not allowed:
        try:
            capture_backend_event(
                get_db(),
                event_name="rate_limit_hit",
                user_id=str(uid),
                user_email=str(user.get("email") or ""),
                session_id=x_session_id,
                properties={
                    "route": "/api/scan-markets",
                    "app_area": "scanner",
                    "limit_key": "scan",
                    "window_seconds": SCAN_RATE_WINDOW_SECONDS,
                    "max_requests": SCAN_RATE_MAX_REQUESTS,
                },
                dedupe_key=f"rate-limit:{uid}:{int(time.time()) // 60}",
            )
        except Exception:
            pass
        raise HTTPException(
            status_code=429,
            detail="Too many scan requests. Please try again in a few minutes.",
        )
    return user


def validate_ops_token(provided_token: str | None, fallback_token: str | None = None) -> None:
    expected = os.getenv("CRON_TOKEN")
    provided = (provided_token if isinstance(provided_token, str) else None) or (
        fallback_token if isinstance(fallback_token, str) else None
    )
    if not provided:
        raise HTTPException(status_code=401, detail="Invalid ops token")
    if not expected:
        raise HTTPException(status_code=503, detail="CRON_TOKEN not configured on server")
    if provided != expected:
        raise HTTPException(status_code=401, detail="Invalid ops token")


def require_ops_token(
    x_ops_token: str | None = Header(default=None, alias="X-Ops-Token"),
    x_cron_token: str | None = Header(default=None, alias="X-Cron-Token"),
) -> None:
    validate_ops_token(x_ops_token, x_cron_token)
