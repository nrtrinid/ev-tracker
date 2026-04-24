from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from database import get_db
from services.analytics_events import (
    capture_analytics_event,
    is_supported_analytics_event,
    normalize_session_id,
)
from services.runtime_support import log_event, retry_supabase


router = APIRouter()


class AnalyticsEventIngestRequest(BaseModel):
    event_name: str = Field(min_length=1, max_length=80)
    session_id: str | None = Field(default=None, max_length=120)
    route: str | None = Field(default=None, max_length=200)
    app_area: str | None = Field(default=None, max_length=40)
    properties: dict[str, Any] = Field(default_factory=dict)
    dedupe_key: str | None = Field(default=None, max_length=180)


def _extract_bearer_token(authorization: str | None) -> str | None:
    if not isinstance(authorization, str):
        return None
    if not authorization.startswith("Bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    return token or None


def _extract_user_email(user: Any) -> str | None:
    if user is None:
        return None

    email = getattr(user, "email", None)
    if not isinstance(email, str):
        if isinstance(user, dict):
            email = user.get("email")
        else:
            raw = getattr(user, "model_dump", None)
            if callable(raw):
                try:
                    dumped = raw()
                except Exception:
                    dumped = None
                if isinstance(dumped, dict):
                    email = dumped.get("email")

    if not isinstance(email, str):
        return None

    normalized = email.strip()
    if not normalized:
        return None
    return normalized[:320]


async def _optional_user_from_authorization(authorization: str | None) -> tuple[str | None, str | None]:
    token = _extract_bearer_token(authorization)
    if not token:
        return None, None

    try:
        supabase = get_db()
        response = await run_in_threadpool(supabase.auth.get_user, token)
        user = response.user
    except Exception:
        return None, None

    if not user or not getattr(user, "id", None):
        return None, None

    return str(user.id), _extract_user_email(user)


@router.post("/analytics/events")
async def ingest_analytics_event(
    payload: AnalyticsEventIngestRequest,
    x_session_id: str | None = Header(default=None, alias="X-Session-ID"),
    authorization: str | None = Header(default=None, alias="Authorization"),
):
    event_name = payload.event_name.strip()
    if not is_supported_analytics_event(event_name):
        raise HTTPException(status_code=422, detail="Unsupported analytics event")

    user_id, user_email = await _optional_user_from_authorization(authorization)
    session_id = normalize_session_id(payload.session_id) or normalize_session_id(x_session_id)

    if not user_id and not session_id:
        raise HTTPException(status_code=422, detail="session_id is required for anonymous analytics events")

    properties = dict(payload.properties or {})
    if user_email:
        # Always set from authenticated identity so clients cannot spoof this field.
        properties["user_email"] = user_email

    db = None
    try:
        db = get_db()
    except Exception:
        # Analytics ingestion is best-effort; route should still return ok=False-style status
        # via inserted flag rather than raising hard infra errors.
        pass

    inserted = capture_analytics_event(
        db=db,
        retry_supabase=retry_supabase,
        log_event=log_event,
        event_name=event_name,
        source="frontend",
        user_id=user_id,
        session_id=session_id,
        route=payload.route,
        app_area=payload.app_area,
        properties=properties,
        dedupe_key=payload.dedupe_key,
    )

    return {
        "ok": True,
        "inserted": inserted,
    }
