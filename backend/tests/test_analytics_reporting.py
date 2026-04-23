from datetime import UTC, datetime

from services.analytics_reporting import summarize_analytics_rows, summarize_analytics_user_rows


def _event(
    event_name: str,
    *,
    session_id: str | None,
    user_id: str | None = None,
    user_email: str | None = None,
    captured_at: str,
) -> dict:
    properties = {}
    if user_email is not None:
        properties["user_email"] = user_email
    return {
        "event_name": event_name,
        "session_id": session_id,
        "user_id": user_id,
        "captured_at": captured_at,
        "properties": properties,
    }


def test_summarize_analytics_rows_filters_internal_events_and_orders_funnel() -> None:
    now = datetime(2026, 4, 7, 12, 0, 0, tzinfo=UTC)
    rows = [
        _event("board_viewed", session_id="s1", user_id="u1", user_email="tester@example.com", captured_at="2026-04-07T09:00:00Z"),
        _event("log_bet_opened", session_id="s1", user_id="u1", user_email="tester@example.com", captured_at="2026-04-07T09:01:00Z"),
        _event("bet_logged", session_id="s1", user_id="u1", user_email="tester@example.com", captured_at="2026-04-07T09:02:00Z"),
        _event("board_viewed", session_id="s2", user_id="u2", user_email="ops@example.com", captured_at="2026-04-07T10:00:00Z"),
        _event("log_bet_opened", session_id="s2", user_id="u2", user_email="ops@example.com", captured_at="2026-04-07T10:01:00Z"),
        _event("bet_logged", session_id="s2", user_id="u2", user_email="ops@example.com", captured_at="2026-04-07T10:02:00Z"),
        _event("log_bet_opened", session_id="s3", user_id="u3", user_email="tester2@example.com", captured_at="2026-04-07T11:00:00Z"),
        _event("bet_logged", session_id="s4", user_id="u4", user_email="tester3@example.com", captured_at="2026-04-07T11:15:00Z"),
        _event("board_viewed", session_id="s5", user_id=None, captured_at="2026-04-07T11:30:00Z"),
    ]

    summary = summarize_analytics_rows(
        rows,
        now_utc=now,
        window_days=7,
        audience="external",
        internal_emails=frozenset({"ops@example.com"}),
        test_emails=frozenset(),
    )

    assert summary["audience"] == "external"
    assert summary["totals"]["events"] == 6
    assert summary["totals"]["sessions"] == 4
    assert summary["totals"]["users"] == 3
    assert summary["event_counts"]["board_viewed"] == 2
    assert summary["event_counts"]["log_bet_opened"] == 2
    assert summary["event_counts"]["bet_logged"] == 2
    assert summary["funnel"]["sessions_with_board_viewed"] == 2
    assert summary["funnel"]["sessions_with_log_bet_opened"] == 1
    assert summary["funnel"]["sessions_with_bet_logged"] == 1
    assert summary["funnel"]["board_to_log_open_rate_pct"] == 50.0
    assert summary["funnel"]["log_open_to_bet_logged_rate_pct"] == 100.0
    assert summary["audience_breakdown"]["excluded_internal_events"] == 3
    assert summary["audience_breakdown"]["excluded_events"] == 3
    assert any("Excluded 3 internal/test events" in warning for warning in summary["quality_warnings"])
    assert any("prior board view" in warning for warning in summary["quality_warnings"])
    assert any("prior ordered log-open" in warning for warning in summary["quality_warnings"])


def test_summarize_analytics_user_rows_filters_internal_users_by_default() -> None:
    now = datetime(2026, 4, 8, 12, 0, 0, tzinfo=UTC)
    rows = [
        _event("tutorial_started", session_id="s1", user_id="u1", user_email="tester@example.com", captured_at="2026-04-07T09:00:00Z"),
        _event("board_viewed", session_id="s1", user_id="u1", user_email="tester@example.com", captured_at="2026-04-07T09:01:00Z"),
        _event("bet_logged", session_id="s1", user_id="u1", user_email="tester@example.com", captured_at="2026-04-07T09:02:00Z"),
        _event("board_viewed", session_id="s2", user_id="u2", user_email="ops@example.com", captured_at="2026-04-07T10:00:00Z"),
        _event("bet_logged", session_id="s2", user_id="u2", user_email="ops@example.com", captured_at="2026-04-07T10:02:00Z"),
        _event("board_viewed", session_id="anon-1", user_id=None, captured_at="2026-04-07T11:00:00Z"),
    ]

    out = summarize_analytics_user_rows(
        rows,
        now_utc=now,
        window_days=7,
        max_users=25,
        timeline_limit=5,
        audience="external",
        internal_emails=frozenset({"ops@example.com"}),
        test_emails=frozenset(),
    )

    assert out["audience"] == "external"
    assert out["totals"]["tracked_users"] == 2
    assert out["audience_breakdown"]["excluded_tracked_users"] == 1
    assert out["audience_breakdown"]["excluded_internal_users"] == 1
    assert all(user.get("user_email") != "ops@example.com" for user in out["users"])
    assert any("Excluded 1 internal/test users" in warning for warning in out["quality_warnings"])


def test_summarize_analytics_user_rows_can_include_all_audiences() -> None:
    now = datetime(2026, 4, 8, 12, 0, 0, tzinfo=UTC)
    rows = [
        _event("board_viewed", session_id="s1", user_id="u1", user_email="tester@example.com", captured_at="2026-04-07T09:01:00Z"),
        _event("board_viewed", session_id="s2", user_id="u2", user_email="ops@example.com", captured_at="2026-04-07T10:00:00Z"),
    ]

    out = summarize_analytics_user_rows(
        rows,
        now_utc=now,
        window_days=7,
        max_users=25,
        timeline_limit=5,
        audience="all",
        internal_emails=frozenset({"ops@example.com"}),
        test_emails=frozenset(),
    )

    assert out["totals"]["tracked_users"] == 2
    assert out["audience_breakdown"]["excluded_tracked_users"] == 0
    assert any(user.get("user_email") == "ops@example.com" for user in out["users"])
