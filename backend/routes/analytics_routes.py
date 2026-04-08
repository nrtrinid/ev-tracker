from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from services.analytics_events import (
    capture_analytics_event,
    is_supported_analytics_event,
    normalize_session_id,
)


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


async def _optional_user_id_from_authorization(authorization: str | None) -> str | None:
    token = _extract_bearer_token(authorization)
    if not token:
        return None

    try:
        import main

        supabase = main.get_db()
        response = await run_in_threadpool(supabase.auth.get_user, token)
        user = response.user
    except Exception:
        return None

    if not user or not user.id:
        return None
    return str(user.id)


@router.post("/analytics/events")
async def ingest_analytics_event(
    payload: AnalyticsEventIngestRequest,
    x_session_id: str | None = Header(default=None, alias="X-Session-ID"),
    authorization: str | None = Header(default=None, alias="Authorization"),
):
    import main

    event_name = payload.event_name.strip()
    if not is_supported_analytics_event(event_name):
        raise HTTPException(status_code=422, detail="Unsupported analytics event")

    user_id = await _optional_user_id_from_authorization(authorization)
    session_id = normalize_session_id(payload.session_id) or normalize_session_id(x_session_id)

    if not user_id and not session_id:
        raise HTTPException(status_code=422, detail="session_id is required for anonymous analytics events")

    inserted = capture_analytics_event(
        db=main.get_db(),
        retry_supabase=main._retry_supabase,
        log_event=main._log_event,
        event_name=event_name,
        source="frontend",
        user_id=user_id,
        session_id=session_id,
        route=payload.route,
        app_area=payload.app_area,
        properties=payload.properties,
        dedupe_key=payload.dedupe_key,
    )

    return {
        "ok": True,
        "inserted": inserted,
    }
