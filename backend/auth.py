"""Authentication helpers and trusted-beta invite-code enforcement."""

import os

from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool

from database import get_db


def _normalize_email(value: str | None) -> str:
    return (value or "").strip().lower()


def parse_email_allowlist(*raw_values: str | None) -> list[str]:
    normalized: list[str] = []
    for raw_value in raw_values:
        for item in (raw_value or "").split(","):
            email = _normalize_email(item)
            if email:
                normalized.append(email)
    return list(dict.fromkeys(normalized))


def _normalize_invite_code(value: str | None) -> str:
    return "".join(ch.lower() for ch in (value or "").strip() if ch.isalnum())


def configured_beta_invite_code() -> str:
    return _normalize_invite_code(os.getenv("BETA_INVITE_CODE"))


def beta_invite_code_enabled() -> bool:
    return bool(configured_beta_invite_code())


def admin_allowlist() -> list[str]:
    return parse_email_allowlist(os.getenv("OPS_ADMIN_EMAILS"))


def is_admin_email(email: str | None) -> bool:
    normalized_email = _normalize_email(email)
    return bool(normalized_email) and normalized_email in admin_allowlist()


def is_valid_beta_invite_code(invite_code: str | None) -> bool:
    expected = configured_beta_invite_code()
    if not expected:
        return True
    return _normalize_invite_code(invite_code) == expected


def _settings_beta_access_granted(user_id: str) -> bool:
    db = get_db()
    result = (
        db.table("settings")
        .select("beta_access_granted")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        return False
    return bool(result.data[0].get("beta_access_granted"))


async def get_current_user_unrestricted(request: Request) -> dict:
    """Extract and validate the Supabase JWT from the Authorization header."""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid authorization header",
        )

    token = auth_header.split(" ", 1)[1]

    try:
        supabase = get_db()
        response = await run_in_threadpool(supabase.auth.get_user, token)
        user = response.user
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    if not user or not user.id:
        raise HTTPException(status_code=401, detail="Token missing user ID")

    return {"id": str(user.id), "email": getattr(user, "email", None)}


def ensure_beta_access(user_id: str, email: str | None) -> None:
    if os.getenv("TESTING") == "1":
        return

    if is_admin_email(email):
        return

    if not beta_invite_code_enabled():
        return

    if _settings_beta_access_granted(user_id):
        return

    raise HTTPException(
        status_code=403,
        detail="Enter the beta invite code to continue.",
    )


async def get_current_user(request: Request) -> dict:
    user = await get_current_user_unrestricted(request)
    ensure_beta_access(user["id"], user.get("email"))
    return user
