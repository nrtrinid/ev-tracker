from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Callable

WEEK1_ANALYTICS_EVENTS: frozenset[str] = frozenset(
    {
        "signup_completed",
        "tutorial_started",
        "tutorial_step_completed",
        "tutorial_skipped",
        "board_viewed",
        "log_bet_opened",
        "bet_logged",
        "bet_log_failed",
        "stale_data_banner_seen",
        "scanner_failed",
        "rate_limit_hit",
        "feedback_submitted",
    }
)

_MAX_PROPERTY_KEYS = 40
_MAX_LIST_ITEMS = 20
_MAX_DEPTH = 4
_MAX_STRING_LEN = 240
_MAX_ROUTE_LEN = 200
_MAX_APP_AREA_LEN = 40
_MAX_SESSION_ID_LEN = 120
_MAX_DEDUPE_KEY_LEN = 180
_MAX_PROPERTIES_JSON_BYTES = 2048


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def is_supported_analytics_event(event_name: str) -> bool:
    return (event_name or "").strip() in WEEK1_ANALYTICS_EVENTS


def normalize_session_id(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized[:_MAX_SESSION_ID_LEN]


def _normalize_route(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized[:_MAX_ROUTE_LEN]


def _normalize_app_area(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    return normalized[:_MAX_APP_AREA_LEN]


def _normalize_dedupe_key(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized[:_MAX_DEDUPE_KEY_LEN]


def _sanitize_value(value: Any, *, depth: int) -> Any:
    if depth > _MAX_DEPTH:
        return None

    if value is None:
        return None

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return value

    if isinstance(value, str):
        return value[:_MAX_STRING_LEN]

    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for idx, (raw_key, raw_value) in enumerate(value.items()):
            if idx >= _MAX_PROPERTY_KEYS:
                break
            if not isinstance(raw_key, str):
                continue
            key = raw_key.strip()
            if not key:
                continue
            key = key[:64]
            sanitized = _sanitize_value(raw_value, depth=depth + 1)
            if sanitized is not None:
                out[key] = sanitized
        return out

    if isinstance(value, (list, tuple)):
        out_list: list[Any] = []
        for idx, item in enumerate(value):
            if idx >= _MAX_LIST_ITEMS:
                break
            sanitized = _sanitize_value(item, depth=depth + 1)
            if sanitized is not None:
                out_list.append(sanitized)
        return out_list

    return None


def sanitize_properties(properties: dict[str, Any] | None) -> dict[str, Any]:
    base = properties if isinstance(properties, dict) else {}
    sanitized = _sanitize_value(base, depth=0)
    if not isinstance(sanitized, dict):
        return {}

    try:
        encoded = json.dumps(sanitized, separators=(",", ":"), ensure_ascii=True)
    except Exception:
        return {}

    if len(encoded.encode("utf-8")) > _MAX_PROPERTIES_JSON_BYTES:
        return {"truncated": True}

    return sanitized


def _run_with_retry(operation: Callable[[], Any], retry_supabase: Callable[[Callable[[], Any]], Any] | None) -> Any:
    if retry_supabase is None:
        return operation()
    return retry_supabase(operation)


def capture_analytics_event(
    *,
    db,
    event_name: str,
    source: str,
    user_id: str | None,
    session_id: str | None,
    route: str | None,
    app_area: str | None,
    properties: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
    retry_supabase: Callable[[Callable[[], Any]], Any] | None = None,
    log_event: Callable[..., None] | None = None,
    captured_at: str | None = None,
) -> bool:
    normalized_event = (event_name or "").strip()
    if not is_supported_analytics_event(normalized_event):
        raise ValueError(f"Unsupported analytics event: {normalized_event}")

    payload = {
        "captured_at": captured_at or _utc_now_iso(),
        "event_name": normalized_event,
        "source": (source or "backend").strip().lower(),
        "user_id": user_id,
        "session_id": normalize_session_id(session_id),
        "route": _normalize_route(route),
        "app_area": _normalize_app_area(app_area),
        "properties": sanitize_properties(properties),
        "dedupe_key": _normalize_dedupe_key(dedupe_key),
    }

    try:
        _run_with_retry(
            lambda: db.table("analytics_events").insert(payload).execute(),
            retry_supabase,
        )
        return True
    except Exception as exc:
        message = str(exc).lower()
        if "duplicate key value" in message and "dedupe" in message:
            return False
        if log_event is not None:
            try:
                log_event(
                    "analytics.capture_failed",
                    level="warning",
                    event_name=normalized_event,
                    error_class=type(exc).__name__,
                    error=str(exc),
                )
            except Exception:
                pass
        return False


def _resolve_runtime_hooks(
    retry_supabase: Callable[[Callable[[], Any]], Any] | None,
    log_event: Callable[..., None] | None,
) -> tuple[Callable[[Callable[[], Any]], Any] | None, Callable[..., None] | None]:
    if retry_supabase is not None and log_event is not None:
        return retry_supabase, log_event

    try:
        import main as main_module

        return (
            retry_supabase or getattr(main_module, "_retry_supabase", None),
            log_event or getattr(main_module, "_log_event", None),
        )
    except Exception:
        return retry_supabase, log_event


def capture_backend_event(
    db,
    *,
    event_name: str,
    user_id: str | None,
    session_id: str | None,
    properties: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
    retry_supabase: Callable[[Callable[[], Any]], Any] | None = None,
    log_event: Callable[..., None] | None = None,
) -> bool:
    payload_properties: dict[str, Any] = dict(properties or {})
    route = payload_properties.pop("route", None)
    app_area = payload_properties.pop("app_area", None)

    resolved_retry, resolved_log = _resolve_runtime_hooks(retry_supabase, log_event)
    try:
        return capture_analytics_event(
            db=db,
            event_name=event_name,
            source="backend",
            user_id=user_id,
            session_id=session_id,
            route=route,
            app_area=app_area,
            properties=payload_properties,
            dedupe_key=dedupe_key,
            retry_supabase=resolved_retry,
            log_event=resolved_log,
        )
    except Exception:
        return False
