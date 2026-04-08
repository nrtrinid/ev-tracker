from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Header

from dependencies import require_current_user
from models import (
    OnboardingEventRequest,
    OnboardingStateResponse,
    SettingsResponse,
    SettingsUpdate,
)
from services.analytics_events import capture_backend_event
from utils.request_context import get_request_id
from services.onboarding_state import (
    apply_onboarding_event as apply_onboarding_event_transition,
    is_valid_onboarding_event,
    is_valid_onboarding_step,
    normalize_onboarding_state,
)


router = APIRouter()


def build_settings_update_payload(settings_update) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if settings_update.k_factor is not None:
        data["k_factor"] = settings_update.k_factor
    if settings_update.default_stake is not None:
        data["default_stake"] = settings_update.default_stake
    if settings_update.preferred_sportsbooks is not None:
        data["preferred_sportsbooks"] = settings_update.preferred_sportsbooks
    if settings_update.kelly_multiplier is not None:
        data["kelly_multiplier"] = settings_update.kelly_multiplier
    if settings_update.bankroll_override is not None:
        data["bankroll_override"] = settings_update.bankroll_override
    if settings_update.use_computed_bankroll is not None:
        data["use_computed_bankroll"] = settings_update.use_computed_bankroll
    if settings_update.k_factor_mode is not None:
        data["k_factor_mode"] = settings_update.k_factor_mode
    if settings_update.k_factor_min_stake is not None:
        data["k_factor_min_stake"] = settings_update.k_factor_min_stake
    if settings_update.k_factor_smoothing is not None:
        data["k_factor_smoothing"] = settings_update.k_factor_smoothing
    if settings_update.k_factor_clamp_min is not None:
        data["k_factor_clamp_min"] = settings_update.k_factor_clamp_min
    if settings_update.k_factor_clamp_max is not None:
        data["k_factor_clamp_max"] = settings_update.k_factor_clamp_max
    if getattr(settings_update, "onboarding_state", None) is not None:
        raise ValueError("onboarding_state updates must use /onboarding/events")
    return data


def _ensure_onboarding_state(
    *,
    db,
    user_id: str,
    settings: dict[str, Any],
    utc_now_iso: Callable[[], str],
) -> dict[str, Any]:
    now_iso = utc_now_iso()
    normalized = normalize_onboarding_state(
        settings.get("onboarding_state"),
        now_iso=now_iso,
        reset_legacy=True,
    )
    if settings.get("onboarding_state") != normalized:
        db.table("settings").update(
            {
                "onboarding_state": normalized,
                "updated_at": now_iso,
            }
        ).eq("user_id", user_id).execute()
    return normalized


def get_settings_impl(
    *,
    user: dict,
    get_db: Callable[[], Any],
    get_user_settings: Callable[[Any, str], dict],
    build_settings_response: Callable[[Any, str, dict], Any],
    utc_now_iso: Callable[[], str],
):
    db = get_db()
    settings = get_user_settings(db, user["id"])
    settings["onboarding_state"] = _ensure_onboarding_state(
        db=db,
        user_id=user["id"],
        settings=settings,
        utc_now_iso=utc_now_iso,
    )
    return build_settings_response(db, user["id"], settings)


def update_settings_impl(
    *,
    settings_update,
    user: dict,
    get_db: Callable[[], Any],
    get_user_settings: Callable[[Any, str], dict],
    build_settings_response: Callable[[Any, str, dict], Any],
    build_update_payload: Callable[[Any], dict[str, Any]],
    utc_now_iso: Callable[[], str],
):
    db = get_db()

    get_user_settings(db, user["id"])
    data = build_update_payload(settings_update)

    if data:
        data["updated_at"] = utc_now_iso()
        db.table("settings").update(data).eq("user_id", user["id"]).execute()

    updated = get_user_settings(db, user["id"])
    updated["onboarding_state"] = _ensure_onboarding_state(
        db=db,
        user_id=user["id"],
        settings=updated,
        utc_now_iso=utc_now_iso,
    )
    return build_settings_response(db, user["id"], updated)


def get_onboarding_state_impl(
    *,
    user: dict,
    get_db: Callable[[], Any],
    get_user_settings: Callable[[Any, str], dict],
    utc_now_iso: Callable[[], str],
) -> dict[str, Any]:
    db = get_db()
    settings = get_user_settings(db, user["id"])
    return _ensure_onboarding_state(
        db=db,
        user_id=user["id"],
        settings=settings,
        utc_now_iso=utc_now_iso,
    )


def apply_onboarding_event_impl(
    *,
    event: OnboardingEventRequest,
    user: dict,
    session_id: str | None = None,
    get_db: Callable[[], Any],
    get_user_settings: Callable[[Any, str], dict],
    utc_now_iso: Callable[[], str],
) -> dict[str, Any]:
    if not is_valid_onboarding_event(event.event):
        raise HTTPException(status_code=422, detail="Unsupported onboarding event")

    if event.event in ("complete_step", "dismiss_step"):
        if event.step is None:
            raise HTTPException(status_code=422, detail="step is required for this onboarding event")
        if not is_valid_onboarding_step(event.step):
            raise HTTPException(status_code=422, detail="Unsupported onboarding step")

    if event.event == "reset" and event.step is not None:
        raise HTTPException(status_code=422, detail="reset event does not accept a step")

    db = get_db()
    settings = get_user_settings(db, user["id"])
    current = _ensure_onboarding_state(
        db=db,
        user_id=user["id"],
        settings=settings,
        utc_now_iso=utc_now_iso,
    )
    now_iso = utc_now_iso()
    next_state = apply_onboarding_event_transition(
        current,
        event=event.event,
        step=event.step,
        now_iso=now_iso,
    )
    if next_state != current:
        db.table("settings").update(
            {
                "onboarding_state": next_state,
                "updated_at": now_iso,
            }
        ).eq("user_id", user["id"]).execute()

        analytics_event_name = None
        if event.event == "complete_step":
            analytics_event_name = "tutorial_step_completed"
        elif event.event == "dismiss_step":
            analytics_event_name = "tutorial_skipped"

        if analytics_event_name:
            capture_backend_event(
                db,
                event_name=analytics_event_name,
                user_id=str(user.get("id") or ""),
                session_id=session_id,
                properties={
                    "route": "/onboarding/events",
                    "app_area": "tutorial",
                    "step": event.step,
                },
                dedupe_key=f"onboarding:{event.event}:{event.step or 'none'}:{user.get('id')}:{get_request_id()}",
            )

    return next_state


@router.get("/settings", response_model=SettingsResponse)
def get_settings(user: dict = Depends(require_current_user)):
    import main

    return get_settings_impl(
        user=user,
        get_db=main.get_db,
        get_user_settings=main.get_user_settings,
        build_settings_response=main._build_settings_response,
        utc_now_iso=main._utc_now_iso,
    )


@router.patch("/settings", response_model=SettingsResponse)
def update_settings(
    settings: SettingsUpdate,
    user: dict = Depends(require_current_user),
):
    import main

    try:
        return update_settings_impl(
            settings_update=settings,
            user=user,
            get_db=main.get_db,
            get_user_settings=main.get_user_settings,
            build_settings_response=main._build_settings_response,
            build_update_payload=build_settings_update_payload,
            utc_now_iso=main._utc_now_iso,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/onboarding/state", response_model=OnboardingStateResponse)
def get_onboarding_state(user: dict = Depends(require_current_user)):
    import main

    return get_onboarding_state_impl(
        user=user,
        get_db=main.get_db,
        get_user_settings=main.get_user_settings,
        utc_now_iso=main._utc_now_iso,
    )


@router.post("/onboarding/events", response_model=OnboardingStateResponse)
def apply_onboarding_event(
    event: OnboardingEventRequest,
    user: dict = Depends(require_current_user),
    session_id: str | None = Header(default=None, alias="X-Session-ID"),
):
    import main

    return apply_onboarding_event_impl(
        event=event,
        user=user,
        session_id=session_id,
        get_db=main.get_db,
        get_user_settings=main.get_user_settings,
        utc_now_iso=main._utc_now_iso,
    )
