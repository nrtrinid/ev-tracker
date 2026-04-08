import os
import time

from fastapi import Depends, Header, HTTPException

from auth import get_current_user
from database import get_db
from services.analytics_events import capture_backend_event
from services.shared_state import allow_fixed_window_rate_limit

SCAN_RATE_WINDOW_SECONDS = 15 * 60
SCAN_RATE_MAX_REQUESTS = 12


def get_db_dependency():
    return get_db()


async def require_current_user(user: dict = Depends(get_current_user)) -> dict:
    return user


def _normalize_email(value: str | None) -> str:
    return (value or "").strip().lower()


def _admin_allowlist() -> list[str]:
    raw = os.getenv("OPS_ADMIN_EMAILS", "")
    return [email for email in (_normalize_email(item) for item in raw.split(",")) if email]


async def require_admin_user(user: dict = Depends(get_current_user)) -> dict:
    allowlist = _admin_allowlist()
    if not allowlist:
        raise HTTPException(status_code=503, detail="OPS_ADMIN_EMAILS not configured")

    email = _normalize_email(user.get("email"))
    if not email or email not in allowlist:
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


def require_ops_token(
    x_ops_token: str | None = Header(default=None, alias="X-Ops-Token"),
    x_cron_token: str | None = Header(default=None, alias="X-Cron-Token"),
) -> None:
    expected = os.getenv("CRON_TOKEN")
    provided = x_ops_token or x_cron_token
    if not provided:
        raise HTTPException(status_code=401, detail="Invalid ops token")
    if not expected:
        raise HTTPException(status_code=503, detail="CRON_TOKEN not configured on server")
    if provided != expected:
        raise HTTPException(status_code=401, detail="Invalid ops token")
