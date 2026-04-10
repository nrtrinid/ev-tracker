from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from services.analytics_events import WEEK1_ANALYTICS_EVENTS


_DECISION_EVENTS: tuple[str, ...] = (
    "signup_completed",
    "tutorial_started",
    "tutorial_step_completed",
    "tutorial_skipped",
    "board_viewed",
    "log_bet_opened",
    "bet_logged",
    "bet_log_failed",
    "scanner_failed",
    "rate_limit_hit",
    "stale_data_banner_seen",
    "feedback_submitted",
)

_DAILY_EVENTS: tuple[str, ...] = (
    "signup_completed",
    "board_viewed",
    "log_bet_opened",
    "bet_logged",
    "bet_log_failed",
    "scanner_failed",
    "rate_limit_hit",
    "feedback_submitted",
)

_FAILURE_EVENTS: frozenset[str] = frozenset(
    {
        "bet_log_failed",
        "scanner_failed",
        "rate_limit_hit",
    }
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso_z(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _parse_captured_at(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _pct(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round((numerator / denominator) * 100.0, 2)


def summarize_analytics_rows(
    rows: list[dict[str, Any]],
    *,
    now_utc: datetime,
    window_days: int,
) -> dict[str, Any]:
    event_counts: dict[str, int] = {event: 0 for event in _DECISION_EVENTS}
    by_day: dict[str, dict[str, int]] = {}
    unique_sessions: set[str] = set()
    unique_users: set[str] = set()
    user_sessions: dict[str, set[str]] = defaultdict(set)
    session_events: dict[str, set[str]] = defaultdict(set)

    for row in rows:
        event_name = str(row.get("event_name") or "").strip()
        if not event_name:
            continue

        if event_name in event_counts:
            event_counts[event_name] += 1

        session_id = row.get("session_id")
        if isinstance(session_id, str) and session_id.strip():
            normalized_session_id = session_id.strip()
            unique_sessions.add(normalized_session_id)
            session_events[normalized_session_id].add(event_name)

        user_id = row.get("user_id")
        if isinstance(user_id, str) and user_id.strip():
            normalized_user_id = user_id.strip()
            unique_users.add(normalized_user_id)
            if isinstance(session_id, str) and session_id.strip():
                user_sessions[normalized_user_id].add(session_id.strip())

        captured_at = _parse_captured_at(row.get("captured_at"))
        if captured_at is None:
            continue
        day_key = captured_at.date().isoformat()
        day_bucket = by_day.setdefault(day_key, {event: 0 for event in _DAILY_EVENTS})
        if event_name in day_bucket:
            day_bucket[event_name] += 1

    sessions_with_board = sum(1 for events in session_events.values() if "board_viewed" in events)
    sessions_with_log_open = sum(1 for events in session_events.values() if "log_bet_opened" in events)
    sessions_with_bet_logged = sum(1 for events in session_events.values() if "bet_logged" in events)

    returning_users = sum(1 for sessions in user_sessions.values() if len(sessions) >= 2)
    known_user_count = len(user_sessions)
    known_user_sessions = sum(len(sessions) for sessions in user_sessions.values())

    failure_denominator = event_counts["bet_logged"] + event_counts["bet_log_failed"]

    daily_rows = [
        {
            "date": day_key,
            "counts": by_day[day_key],
        }
        for day_key in sorted(by_day.keys())
    ]

    return {
        "window_days": window_days,
        "generated_at": _iso_z(now_utc),
        "since": _iso_z(now_utc - timedelta(days=window_days)),
        "totals": {
            "events": len(rows),
            "sessions": len(unique_sessions),
            "users": len(unique_users),
        },
        "event_counts": event_counts,
        "funnel": {
            "sessions_with_board_viewed": sessions_with_board,
            "sessions_with_log_bet_opened": sessions_with_log_open,
            "sessions_with_bet_logged": sessions_with_bet_logged,
            "board_to_log_open_rate_pct": _pct(sessions_with_log_open, sessions_with_board),
            "log_open_to_bet_logged_rate_pct": _pct(sessions_with_bet_logged, sessions_with_log_open),
        },
        "reliability": {
            "scanner_failed": event_counts["scanner_failed"],
            "rate_limit_hit": event_counts["rate_limit_hit"],
            "stale_data_banner_seen": event_counts["stale_data_banner_seen"],
            "bet_log_failed": event_counts["bet_log_failed"],
            "bet_log_failed_rate_pct": _pct(event_counts["bet_log_failed"], failure_denominator),
        },
        "return_usage": {
            "returning_users": returning_users,
            "returning_user_rate_pct": _pct(returning_users, known_user_count),
            "avg_sessions_per_known_user": (
                round(known_user_sessions / known_user_count, 2) if known_user_count > 0 else None
            ),
        },
        "daily": daily_rows,
    }


def _trimmed_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized if normalized else None


def _email_from_row(row: dict[str, Any]) -> str | None:
    properties = row.get("properties")
    if not isinstance(properties, dict):
        return None

    for key in ("user_email", "email", "userEmail"):
        candidate = _trimmed_str(properties.get(key))
        if candidate and "@" in candidate and len(candidate) <= 200:
            return candidate
    return None


def _actor_key(user_id: str | None, session_id: str | None) -> str | None:
    if user_id:
        return f"user:{user_id}"
    if session_id:
        return f"anon:{session_id}"
    return None


def _compact_id(value: str, keep: int = 6) -> str:
    if len(value) <= keep * 2 + 1:
        return value
    return f"{value[:keep]}...{value[-keep:]}"


def summarize_analytics_user_rows(
    rows: list[dict[str, Any]],
    *,
    now_utc: datetime,
    window_days: int,
    max_users: int,
    timeline_limit: int,
) -> dict[str, Any]:
    safe_max_users = max(1, min(100, int(max_users)))
    safe_timeline_limit = max(1, min(30, int(timeline_limit)))

    grouped: dict[str, dict[str, Any]] = {}

    for row in rows:
        event_name = _trimmed_str(row.get("event_name"))
        captured_at = _parse_captured_at(row.get("captured_at"))
        if not event_name or captured_at is None:
            continue

        user_id = _trimmed_str(row.get("user_id"))
        user_email = _email_from_row(row)
        session_id = _trimmed_str(row.get("session_id"))
        actor_key = _actor_key(user_id, session_id)
        if actor_key is None:
            continue

        bucket = grouped.setdefault(
            actor_key,
            {
                "actor_key": actor_key,
                "user_id": user_id,
                "user_email": user_email,
                "entries": [],
            },
        )
        if bucket.get("user_id") is None and user_id is not None:
            bucket["user_id"] = user_id
        if bucket.get("user_email") is None and user_email is not None:
            bucket["user_email"] = user_email

        bucket["entries"].append(
            {
                "captured_at_dt": captured_at,
                "event_name": event_name,
                "session_id": session_id,
                "route": _trimmed_str(row.get("route")),
                "app_area": _trimmed_str(row.get("app_area")),
            }
        )

    users: list[dict[str, Any]] = []
    for bucket in grouped.values():
        entries: list[dict[str, Any]] = bucket["entries"]
        entries.sort(key=lambda item: item["captured_at_dt"])
        if not entries:
            continue

        def first_event_at(event: str) -> datetime | None:
            for entry in entries:
                if entry["event_name"] == event:
                    return entry["captured_at_dt"]
            return None

        first_seen_at = entries[0]["captured_at_dt"]
        last_seen_at = entries[-1]["captured_at_dt"]

        latest_session_id = next((entry["session_id"] for entry in reversed(entries) if entry["session_id"]), None)
        latest_session_entries = [entry for entry in entries if latest_session_id and entry["session_id"] == latest_session_id]
        latest_session_last_event_at = latest_session_entries[-1]["captured_at_dt"] if latest_session_entries else None

        session_ids = {entry["session_id"] for entry in entries if entry["session_id"]}
        total_bets_logged = sum(1 for entry in entries if entry["event_name"] == "bet_logged")
        failure_entries = [entry for entry in entries if entry["event_name"] in _FAILURE_EVENTS]
        last_error = failure_entries[-1] if failure_entries else None

        tutorial_started_at = first_event_at("tutorial_started")
        tutorial_completed_at = first_event_at("tutorial_step_completed")
        tutorial_skipped_at = first_event_at("tutorial_skipped")
        first_board_view_at = first_event_at("board_viewed")
        first_log_open_at = first_event_at("log_bet_opened")
        first_bet_logged_at = first_event_at("bet_logged")

        if tutorial_skipped_at is not None:
            tutorial_status = "skipped"
        elif tutorial_completed_at is not None:
            tutorial_status = "completed"
        elif tutorial_started_at is not None:
            tutorial_status = "started"
        else:
            tutorial_status = "not_started"

        days_since_last_seen = max(0.0, (now_utc - last_seen_at).total_seconds() / 86400.0)
        has_recent_error = bool(
            last_error
            and (now_utc - last_error["captured_at_dt"]) <= timedelta(days=3)
        )

        if days_since_last_seen > 7:
            follow_up_tag = "inactive"
            follow_up_reason = "No activity in 7+ days."
            activity_status = "silent"
        elif has_recent_error:
            follow_up_tag = "recent_failure"
            follow_up_reason = "Recent reliability failure detected."
            activity_status = "stuck"
        elif first_board_view_at is not None and first_bet_logged_at is None:
            follow_up_tag = "stuck_pre_bet"
            follow_up_reason = "Viewed board but has not logged a bet."
            activity_status = "stuck"
        elif total_bets_logged >= 3:
            follow_up_tag = "high_signal_tester"
            follow_up_reason = "Consistent bettor with repeat activity."
            activity_status = "active"
        else:
            follow_up_tag = "active"
            follow_up_reason = "Active with no current blocker signal."
            activity_status = "active"

        user_id = bucket.get("user_id")
        user_email = bucket.get("user_email")
        actor_id = user_id or latest_session_id or bucket["actor_key"]
        user_label = _compact_id(actor_id)

        latest_entries = list(reversed(entries))[:safe_timeline_limit]
        timeline = [
            {
                "captured_at": _iso_z(entry["captured_at_dt"]),
                "event_name": entry["event_name"],
                "session_id": entry["session_id"],
                "route": entry["route"],
                "app_area": entry["app_area"],
                "is_failure": entry["event_name"] in _FAILURE_EVENTS,
            }
            for entry in latest_entries
        ]

        users.append(
            {
                "actor_key": bucket["actor_key"],
                "user_id": user_id,
                "user_email": user_email,
                "user_label": user_label,
                "is_anonymous": user_id is None,
                "joined_at": _iso_z(first_seen_at),
                "last_seen_at": _iso_z(last_seen_at),
                "tutorial_status": tutorial_status,
                "tutorial_started_at": _iso_z(tutorial_started_at) if tutorial_started_at else None,
                "tutorial_completed_at": _iso_z(tutorial_completed_at) if tutorial_completed_at else None,
                "tutorial_skipped_at": _iso_z(tutorial_skipped_at) if tutorial_skipped_at else None,
                "first_board_view_at": _iso_z(first_board_view_at) if first_board_view_at else None,
                "first_log_open_at": _iso_z(first_log_open_at) if first_log_open_at else None,
                "first_bet_logged_at": _iso_z(first_bet_logged_at) if first_bet_logged_at else None,
                "latest_session": {
                    "session_id": latest_session_id,
                    "event_count": len(latest_session_entries),
                    "last_event_at": _iso_z(latest_session_last_event_at) if latest_session_last_event_at else None,
                },
                "total_sessions": len(session_ids),
                "total_bets_logged": total_bets_logged,
                "failures_hit": len(failure_entries),
                "last_error_event": last_error["event_name"] if last_error else None,
                "last_error_at": _iso_z(last_error["captured_at_dt"]) if last_error else None,
                "follow_up_tag": follow_up_tag,
                "follow_up_reason": follow_up_reason,
                "activity_status": activity_status,
                "timeline": timeline,
            }
        )

    priority = {
        "recent_failure": 0,
        "stuck_pre_bet": 1,
        "inactive": 2,
        "high_signal_tester": 3,
        "active": 4,
    }

    users.sort(
        key=lambda item: (
            priority.get(str(item.get("follow_up_tag")), 9),
            -int(parse_dt.timestamp())
            if (parse_dt := _parse_captured_at(item.get("last_seen_at"))) is not None
            else 0,
        )
    )

    visible_users = users[:safe_max_users]
    active_last_24h = sum(
        1
        for user in users
        if (parsed := _parse_captured_at(user.get("last_seen_at"))) is not None
        and (now_utc - parsed) <= timedelta(hours=24)
    )

    return {
        "window_days": window_days,
        "generated_at": _iso_z(now_utc),
        "since": _iso_z(now_utc - timedelta(days=window_days)),
        "totals": {
            "tracked_users": len(users),
            "identified_users": sum(1 for user in users if not user.get("is_anonymous")),
            "anonymous_users": sum(1 for user in users if user.get("is_anonymous")),
            "active_last_24h": active_last_24h,
            "needs_follow_up": sum(
                1
                for user in users
                if str(user.get("follow_up_tag")) in {"recent_failure", "stuck_pre_bet", "inactive"}
            ),
            "stuck_users": sum(1 for user in users if str(user.get("activity_status")) == "stuck"),
            "silent_users": sum(1 for user in users if str(user.get("activity_status")) == "silent"),
            "users_with_recent_failures": sum(
                1 for user in users if str(user.get("follow_up_tag")) == "recent_failure"
            ),
        },
        "returned_users": len(visible_users),
        "has_more": len(users) > len(visible_users),
        "users": visible_users,
    }


def _fetch_analytics_rows(
    *,
    db,
    since_iso: str,
    retry_supabase: Callable[[Callable[[], Any]], Any] | None,
    page_size: int = 1000,
    max_rows: int = 20000,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    while len(rows) < max_rows:
        query = (
            db.table("analytics_events")
            .select("captured_at,event_name,user_id,session_id,route,app_area,properties")
            .gte("captured_at", since_iso)
            .in_("event_name", list(WEEK1_ANALYTICS_EVENTS))
            .order("captured_at", desc=False)
            .range(offset, offset + page_size - 1)
        )
        if retry_supabase is None:
            response = query.execute()
        else:
            response = retry_supabase(lambda: query.execute())

        batch = response.data or []
        if not batch:
            break

        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size

    if len(rows) > max_rows:
        return rows[:max_rows]
    return rows


def get_weekly_analytics_summary(
    *,
    db,
    window_days: int,
    retry_supabase: Callable[[Callable[[], Any]], Any] | None = None,
) -> dict[str, Any]:
    safe_window_days = max(1, min(30, int(window_days)))
    now_utc = _utc_now()
    since_utc = now_utc - timedelta(days=safe_window_days)
    since_iso = _iso_z(since_utc)

    rows = _fetch_analytics_rows(
        db=db,
        since_iso=since_iso,
        retry_supabase=retry_supabase,
    )
    return summarize_analytics_rows(rows, now_utc=now_utc, window_days=safe_window_days)


def get_weekly_analytics_user_drilldown(
    *,
    db,
    window_days: int,
    max_users: int = 25,
    timeline_limit: int = 12,
    retry_supabase: Callable[[Callable[[], Any]], Any] | None = None,
) -> dict[str, Any]:
    safe_window_days = max(1, min(30, int(window_days)))
    safe_max_users = max(1, min(100, int(max_users)))
    safe_timeline_limit = max(1, min(30, int(timeline_limit)))

    now_utc = _utc_now()
    since_utc = now_utc - timedelta(days=safe_window_days)
    since_iso = _iso_z(since_utc)

    rows = _fetch_analytics_rows(
        db=db,
        since_iso=since_iso,
        retry_supabase=retry_supabase,
    )

    return summarize_analytics_user_rows(
        rows,
        now_utc=now_utc,
        window_days=safe_window_days,
        max_users=safe_max_users,
        timeline_limit=safe_timeline_limit,
    )
