from __future__ import annotations

import json
import os
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

ANALYTICS_AUDIENCE_EXTERNAL = "external"
ANALYTICS_AUDIENCE_ALL = "all"
EXTERNAL_ANALYTICS_EXCLUDED_CLASSES: frozenset[str] = frozenset({"internal", "test"})


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def normalize_analytics_audience(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized == ANALYTICS_AUDIENCE_ALL:
        return ANALYTICS_AUDIENCE_ALL
    return ANALYTICS_AUDIENCE_EXTERNAL


def is_supported_analytics_event(event_name: str) -> bool:
    return (event_name or "").strip() in WEEK1_ANALYTICS_EVENTS


def _trimmed_string(value: Any, *, lower: bool = False) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized.lower() if lower else normalized


def _normalize_email(value: Any) -> str | None:
    return _trimmed_string(value, lower=True)


def parse_email_allowlist(raw: str | None) -> frozenset[str]:
    if not isinstance(raw, str):
        return frozenset()
    return frozenset(
        normalized
        for normalized in (_normalize_email(item) for item in raw.split(","))
        if normalized
    )


def get_internal_analytics_emails(raw: str | None = None) -> frozenset[str]:
    return parse_email_allowlist(raw if raw is not None else os.getenv("OPS_ADMIN_EMAILS"))


def get_test_analytics_emails(raw: str | None = None) -> frozenset[str]:
    return parse_email_allowlist(raw if raw is not None else os.getenv("ANALYTICS_TEST_EMAILS"))


def extract_analytics_email(properties: dict[str, Any] | None) -> str | None:
    if not isinstance(properties, dict):
        return None
    for key in ("user_email", "email", "userEmail"):
        candidate = _normalize_email(properties.get(key))
        if candidate and "@" in candidate and len(candidate) <= 320:
            return candidate
    return None


def classify_analytics_row(
    *,
    user_id: str | None,
    session_id: str | None,
    properties: dict[str, Any] | None,
    internal_emails: frozenset[str] | None = None,
    test_emails: frozenset[str] | None = None,
) -> str:
    normalized_user_id = _trimmed_string(user_id)
    normalized_session_id = normalize_session_id(session_id)
    email = extract_analytics_email(properties)

    internal = internal_emails if internal_emails is not None else get_internal_analytics_emails()
    tests = test_emails if test_emails is not None else get_test_analytics_emails()

    if email and email in internal:
        return "internal"
    if email and email in tests:
        return "test"
    if normalized_user_id:
        return "tester"
    if normalized_session_id:
        return "anonymous"
    return "unknown"


def is_excluded_from_external_analytics(account_class: str) -> bool:
    return str(account_class or "").strip().lower() in EXTERNAL_ANALYTICS_EXCLUDED_CLASSES


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


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        normalized = value.strip().removesuffix("%")
        if not normalized:
            return None
        try:
            return float(normalized)
        except ValueError:
            return None
    return None


def edge_bucket_for_ev_percentage(value: Any) -> str | None:
    ev_percentage = _coerce_float(value)
    if ev_percentage is None:
        return None
    if ev_percentage < 0.5:
        return "0-0.5%"
    if ev_percentage < 1.0:
        return "0.5-1%"
    if ev_percentage < 2.0:
        return "1-2%"
    if ev_percentage < 4.0:
        return "2-4%"
    return "4%+"


def _canonicalize_properties(properties: dict[str, Any]) -> dict[str, Any]:
    out = dict(properties)

    origin_surface = _trimmed_string(out.get("origin_surface")) or _trimmed_string(out.get("surface"))
    if origin_surface and "origin_surface" not in out:
        out["origin_surface"] = origin_surface

    book = _trimmed_string(out.get("book")) or _trimmed_string(out.get("sportsbook"))
    if book and "book" not in out:
        out["book"] = book

    market = (
        _trimmed_string(out.get("market"))
        or _trimmed_string(out.get("source_market_key"))
        or _trimmed_string(out.get("market_key"))
    )
    if market and "market" not in out:
        out["market"] = market

    opportunity_id = (
        _trimmed_string(out.get("opportunity_id"))
        or _trimmed_string(out.get("opportunity_key"))
        or _trimmed_string(out.get("source_selection_key"))
        or _trimmed_string(out.get("selection_key"))
    )
    if opportunity_id and "opportunity_id" not in out:
        out["opportunity_id"] = opportunity_id

    edge_bucket = _trimmed_string(out.get("edge_bucket")) or edge_bucket_for_ev_percentage(
        out.get("ev_percentage", out.get("scan_ev_percent_at_log"))
    )
    if edge_bucket and "edge_bucket" not in out:
        out["edge_bucket"] = edge_bucket

    user_email = extract_analytics_email(out)
    if user_email:
        out["user_email"] = user_email

    return out


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
    base = _canonicalize_properties(properties) if isinstance(properties, dict) else {}
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
        from services.runtime_support import log_event as runtime_log_event
        from services.runtime_support import retry_supabase as runtime_retry_supabase

        return (
            retry_supabase or runtime_retry_supabase,
            log_event or runtime_log_event,
        )
    except Exception:
        return retry_supabase, log_event


def capture_backend_event(
    db,
    *,
    event_name: str,
    user_id: str | None,
    user_email: str | None = None,
    session_id: str | None,
    properties: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
    retry_supabase: Callable[[Callable[[], Any]], Any] | None = None,
    log_event: Callable[..., None] | None = None,
) -> bool:
    payload_properties: dict[str, Any] = dict(properties or {})
    route = payload_properties.pop("route", None)
    app_area = payload_properties.pop("app_area", None)
    normalized_email = _normalize_email(user_email)
    if normalized_email:
        payload_properties["user_email"] = normalized_email

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
