"""
Authentication module.
Validates Supabase JWT via supabase.auth.get_user(token).
"""

from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool

from database import get_db


async def get_current_user(request: Request) -> dict:
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
