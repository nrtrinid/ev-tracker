from datetime import UTC, datetime

from services.analytics_reporting import summarize_analytics_rows, summarize_analytics_user_rows


def _event(event_name: str, *, session_id: str, user_id: str | None = None, captured_at: str) -> dict:
    return {
        "event_name": event_name,
        "session_id": session_id,
        "user_id": user_id,
        "captured_at": captured_at,
    }


def test_summarize_analytics_rows_funnel_and_reliability() -> None:
    now = datetime(2026, 4, 7, 12, 0, 0, tzinfo=UTC)
    rows = [
        _event("board_viewed", session_id="s1", user_id="u1", captured_at="2026-04-07T09:00:00Z"),
        _event("log_bet_opened", session_id="s1", user_id="u1", captured_at="2026-04-07T09:01:00Z"),
        _event("bet_logged", session_id="s1", user_id="u1", captured_at="2026-04-07T09:02:00Z"),
        _event("board_viewed", session_id="s2", user_id="u2", captured_at="2026-04-07T10:00:00Z"),
        _event("log_bet_opened", session_id="s2", user_id="u2", captured_at="2026-04-07T10:01:00Z"),
        _event("bet_log_failed", session_id="s2", user_id="u2", captured_at="2026-04-07T10:02:00Z"),
        _event("scanner_failed", session_id="s3", user_id=None, captured_at="2026-04-07T11:00:00Z"),
    ]

    summary = summarize_analytics_rows(rows, now_utc=now, window_days=7)

    assert summary["totals"]["events"] == 7
    assert summary["totals"]["sessions"] == 3
    assert summary["totals"]["users"] == 2

    assert summary["event_counts"]["board_viewed"] == 2
    assert summary["event_counts"]["log_bet_opened"] == 2
    assert summary["event_counts"]["bet_logged"] == 1
    assert summary["event_counts"]["bet_log_failed"] == 1

    assert summary["funnel"]["sessions_with_board_viewed"] == 2
    assert summary["funnel"]["sessions_with_log_bet_opened"] == 2
    assert summary["funnel"]["sessions_with_bet_logged"] == 1
    assert summary["funnel"]["board_to_log_open_rate_pct"] == 100.0
    assert summary["funnel"]["log_open_to_bet_logged_rate_pct"] == 50.0

    assert summary["reliability"]["scanner_failed"] == 1
    assert summary["reliability"]["bet_log_failed"] == 1
    assert summary["reliability"]["bet_log_failed_rate_pct"] == 50.0

    assert summary["daily"]
    assert summary["daily"][0]["date"] == "2026-04-07"

    assert summary["return_usage"]["returning_users"] == 0
    assert summary["return_usage"]["returning_user_rate_pct"] == 0.0


def test_summarize_analytics_user_rows_flags_follow_up_and_timeline() -> None:
    now = datetime(2026, 4, 8, 12, 0, 0, tzinfo=UTC)
    rows = [
        _event("tutorial_started", session_id="s1", user_id="u1", captured_at="2026-04-07T09:00:00Z"),
        _event("board_viewed", session_id="s1", user_id="u1", captured_at="2026-04-07T09:01:00Z"),
        _event("log_bet_opened", session_id="s1", user_id="u1", captured_at="2026-04-07T09:02:00Z"),
        _event("bet_log_failed", session_id="s1", user_id="u1", captured_at="2026-04-07T09:03:00Z"),
        _event("board_viewed", session_id="s2", user_id="u2", captured_at="2026-03-25T10:00:00Z"),
        _event("bet_logged", session_id="s2", user_id="u2", captured_at="2026-03-25T10:02:00Z"),
    ]

    out = summarize_analytics_user_rows(
        rows,
        now_utc=now,
        window_days=7,
        max_users=25,
        timeline_limit=5,
    )

    assert out["totals"]["tracked_users"] == 2
    assert out["totals"]["needs_follow_up"] >= 1
    assert out["users"]

    first_user = out["users"][0]
    assert first_user["follow_up_tag"] in {"recent_failure", "stuck_pre_bet", "inactive"}
    assert isinstance(first_user["timeline"], list)
    assert len(first_user["timeline"]) >= 1
