"""Canonical scheduler and background job runtime."""

from __future__ import annotations

import asyncio
import os
import time
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from database import get_db
from services import ops_runtime
from services.paper_autolog_runner import (
    is_paper_experiment_autolog_enabled,
    run_longshot_autolog_for_sides,
)
from services.runtime_support import app_role, log_event, new_run_id, retry_supabase, utc_now_iso
from services.scan_runtime import piggyback_clv

SCHEDULED_SCAN_TEMP_TIME_ENV = "SCHEDULED_SCAN_TEMP_TIME_PHOENIX"
DISCORD_SCAN_ALERT_MODE_ENV = "DISCORD_SCAN_ALERT_MODE"
DISCORD_SCAN_ALERT_MODE_TIMED_PING = "timed_ping"
DISCORD_SCAN_ALERT_MODE_EDGE_LIVE = "edge_live"
SCHEDULED_SCAN_WINDOWS_MST: list[tuple[int, int, str]] = [
    (9, 30, "Early-Look / Injury-Watch Scan"),
    (15, 0, "Final Board / Bet Placement Scan"),
]
SCHEDULED_BOARD_DROP_ALERT_GRACE_MINUTES_ENV = "SCHEDULED_BOARD_DROP_ALERT_GRACE_MINUTES"
DEFAULT_SCHEDULED_BOARD_DROP_ALERT_GRACE_MINUTES = 30

PHOENIX_TZ = None
try:
    PHOENIX_TZ = ZoneInfo("America/Phoenix")
except Exception as exc:
    print(f"[Scheduler] Failed to load America/Phoenix timezone: {exc}")


def parse_hhmm(value: str | None) -> tuple[int, int] | None:
    raw = (value or "").strip()
    if not raw:
        return None
    parts = raw.split(":")
    if len(parts) != 2:
        return None
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return None
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return (hour, minute)


def scheduled_board_drop_alert_grace_minutes() -> int:
    raw = (os.getenv(SCHEDULED_BOARD_DROP_ALERT_GRACE_MINUTES_ENV) or "").strip()
    if not raw:
        return DEFAULT_SCHEDULED_BOARD_DROP_ALERT_GRACE_MINUTES
    try:
        minutes = int(raw)
    except ValueError:
        return DEFAULT_SCHEDULED_BOARD_DROP_ALERT_GRACE_MINUTES
    return max(1, minutes)


def scan_alert_mode_raw() -> str:
    return (os.getenv(DISCORD_SCAN_ALERT_MODE_ENV) or DISCORD_SCAN_ALERT_MODE_TIMED_PING).strip().lower()


def scan_alert_mode() -> str:
    raw = scan_alert_mode_raw()
    if raw in {DISCORD_SCAN_ALERT_MODE_TIMED_PING, DISCORD_SCAN_ALERT_MODE_EDGE_LIVE}:
        return raw
    return DISCORD_SCAN_ALERT_MODE_TIMED_PING


def scheduled_scan_window(now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(UTC)
    local_now = current.astimezone(PHOENIX_TZ) if PHOENIX_TZ is not None else current
    minute_of_day = (local_now.hour * 60) + local_now.minute

    hour, minute, label = min(
        SCHEDULED_SCAN_WINDOWS_MST,
        key=lambda window: abs(minute_of_day - ((window[0] * 60) + window[1])),
    )
    anchor_minute_of_day = (hour * 60) + minute
    minutes_from_anchor = minute_of_day - anchor_minute_of_day
    alert_grace_minutes = scheduled_board_drop_alert_grace_minutes()
    return {
        "label": label,
        "anchor_timezone": "America/Phoenix",
        "anchor_time_mst": f"{hour:02d}:{minute:02d}",
        "minutes_from_anchor": minutes_from_anchor,
        "alert_grace_minutes": alert_grace_minutes,
        "alert_window_fresh": abs(minutes_from_anchor) <= alert_grace_minutes,
    }


async def run_jit_clv_snatcher_job() -> None:
    from services.odds_api import run_jit_clv_snatcher

    run_id = new_run_id("jit_clv")
    started_at = time.monotonic()
    ops_runtime.record_scheduler_heartbeat("jit_clv", run_id, "started")
    log_event("scheduler.jit_clv.started", run_id=run_id)
    db = get_db()
    try:
        updated = await run_jit_clv_snatcher(db)
        duration_ms = round((time.monotonic() - started_at) * 1000, 2)
        log_event("scheduler.jit_clv.completed", run_id=run_id, updated=updated, duration_ms=duration_ms)
        ops_runtime.record_scheduler_heartbeat("jit_clv", run_id, "success", duration_ms=duration_ms)
        if updated:
            print(f"[JIT CLV] Captured closing lines for {updated} bet(s).")
            if os.getenv("DISCORD_AUTO_SETTLE_HEARTBEAT") == "1":
                from services.discord_alerts import send_discord_webhook

                payload = {
                    "embeds": [
                        {
                            "title": "JIT CLV update",
                            "description": f"Captured closing lines for **{updated}** bet(s).",
                            "fields": [{"name": "Time (UTC)", "value": utc_now_iso(), "inline": True}],
                        }
                    ]
                }
                asyncio.create_task(send_discord_webhook(payload, message_type="heartbeat"))
    except Exception as exc:
        duration_ms = round((time.monotonic() - started_at) * 1000, 2)
        ops_runtime.record_scheduler_heartbeat("jit_clv", run_id, "failure", duration_ms=duration_ms, error=str(exc))
        log_event(
            "scheduler.jit_clv.failed",
            level="error",
            run_id=run_id,
            error_class=type(exc).__name__,
            error=str(exc),
            duration_ms=duration_ms,
        )


async def run_auto_settler_job() -> None:
    from services.odds_api import get_last_auto_settler_summary, run_auto_settler

    run_id = new_run_id("auto_settler")
    started = utc_now_iso()
    started_at = time.monotonic()
    ops_runtime.record_scheduler_heartbeat("auto_settler", run_id, "started")
    log_event("scheduler.auto_settler.started", run_id=run_id)
    db = get_db()
    try:
        settled = await run_auto_settler(db, source="auto_settle_scheduler")
        finished = utc_now_iso()
        duration_ms = round((time.monotonic() - started_at) * 1000, 2)
        log_event("scheduler.auto_settler.completed", run_id=run_id, settled=settled, duration_ms=duration_ms)
        ops_runtime.record_scheduler_heartbeat("auto_settler", run_id, "success", duration_ms=duration_ms)
        ops_runtime.set_ops_status(
            "last_auto_settle",
            {
                "source": "scheduler",
                "run_id": run_id,
                "started_at": started,
                "finished_at": finished,
                "settled": settled,
                "duration_ms": duration_ms,
                "captured_at": finished,
            },
        )
        summary = get_last_auto_settler_summary()
        if summary:
            ops_runtime.set_ops_status("last_auto_settle_summary", summary)
        summary_meta = None
        if isinstance(summary, dict):
            summary_meta = {}
            if isinstance(summary.get("sports"), list):
                summary_meta["sports"] = summary.get("sports")
            if isinstance(summary.get("manual_settlement_pending"), dict):
                summary_meta["manual_settlement_pending"] = summary.get("manual_settlement_pending")
            for key in ("ml_settled", "props_settled", "parlays_settled", "pickem_research_settled"):
                if summary.get(key) is not None:
                    summary_meta[key] = summary.get(key)
            if not summary_meta:
                summary_meta = None
        ops_runtime.persist_ops_job_run(
            job_kind="auto_settle",
            source="scheduler",
            status="completed",
            run_id=run_id,
            captured_at=finished,
            started_at=started,
            finished_at=finished,
            duration_ms=duration_ms,
            settled=settled,
            skipped_totals=summary.get("skipped_totals") if isinstance(summary, dict) else None,
            meta=summary_meta,
        )
        if os.getenv("DISCORD_AUTO_SETTLE_HEARTBEAT") == "1":
            from services.discord_alerts import send_discord_webhook

            payload = {
                "embeds": [
                    {
                        "title": "Auto-settle run complete",
                        "description": f"Graded **{settled}** bet(s).",
                        "fields": [
                            {"name": "Source", "value": "scheduler", "inline": True},
                            {"name": "Run id", "value": run_id, "inline": True},
                            {"name": "Duration", "value": f"{duration_ms} ms", "inline": True},
                        ],
                    }
                ]
            }
            asyncio.create_task(send_discord_webhook(payload, message_type="heartbeat"))
    except Exception as exc:
        duration_ms = round((time.monotonic() - started_at) * 1000, 2)
        ops_runtime.record_scheduler_heartbeat("auto_settler", run_id, "failure", duration_ms=duration_ms, error=str(exc))
        log_event(
            "scheduler.auto_settler.failed",
            level="error",
            run_id=run_id,
            error_class=type(exc).__name__,
            error=str(exc),
            duration_ms=duration_ms,
        )


async def run_scheduled_board_drop_job(*, alert_delivery_allowed: bool = False) -> None:
    from services.daily_board import run_daily_board_drop
    from services.discord_alerts import (
        DiscordDeliveryError,
        build_board_drop_alert_payload,
        get_last_schedule_stats,
        schedule_alerts,
        send_discord_webhook,
    )

    run_id = new_run_id("scheduled_board_drop")
    started = datetime.now(UTC).isoformat()
    started_at = time.monotonic()
    scan_window = scheduled_scan_window()
    alert_window_fresh = bool(scan_window.get("alert_window_fresh", True))
    use_alert_route = bool(alert_delivery_allowed and alert_window_fresh)
    alert_mode = scan_alert_mode()
    ops_runtime.record_scheduler_heartbeat("scheduled_scan", run_id, "started")
    log_event(
        "scheduler.board_drop.started",
        run_id=run_id,
        started_at=started + "Z",
        scan_window=scan_window,
        scan_alert_mode=alert_mode,
        alert_window_fresh=alert_window_fresh,
        alert_delivery_allowed=alert_delivery_allowed,
        alert_route_selected=use_alert_route,
    )

    alerts_scheduled = 0
    hard_errors = 0
    fresh_straight_sides: list[dict] = []
    fresh_prop_sides: list[dict] = []
    alert_skip_totals = {
        "skipped_memory_dedupe": 0,
        "skipped_shared_dedupe": 0,
        "skipped_threshold": 0,
    }
    board_alert = {
        "attempted": False,
        "delivery_status": "not_attempted",
        "status_code": None,
        "route_kind": None,
        "webhook_source": None,
        "error": None,
    }
    result: dict[str, Any] = {
        "straight_sides": 0,
        "props_sides": 0,
        "featured_games_count": 0,
        "game_line_sports_scanned": [],
        "game_lines_events_fetched": 0,
        "game_lines_events_with_both_books": 0,
        "game_lines_api_requests_remaining": None,
        "props_events_fetched": 0,
        "props_events_with_both_books": 0,
        "props_api_requests_remaining": None,
        "props_events_scanned": 0,
    }

    try:
        result = await run_daily_board_drop(
            db=get_db(),
            source="scheduled_board_drop",
            scan_label=scan_window["label"],
            mst_anchor_time=scan_window["anchor_time_mst"],
            retry_supabase=retry_supabase,
            log_event=log_event,
        )
        fresh_straight_sides = [
            side for side in (result.get("fresh_straight_sides") or []) if isinstance(side, dict)
        ]
        fresh_prop_sides = [
            side for side in (result.get("fresh_prop_sides") or []) if isinstance(side, dict)
        ]
        fresh_sides = [*fresh_straight_sides, *fresh_prop_sides]

        if fresh_sides:
            try:
                await piggyback_clv(fresh_sides)
            except Exception as exc:
                log_event(
                    "scheduler.board_drop.clv_piggyback_failed",
                    level="warning",
                    run_id=run_id,
                    error_class=type(exc).__name__,
                    error=str(exc),
                )

        candidates_seen = len(fresh_sides)
        if alert_mode == DISCORD_SCAN_ALERT_MODE_EDGE_LIVE:
            notification_message_type = "alert" if use_alert_route else "heartbeat"
            notification_delivery_context = "scheduled_board_drop" if use_alert_route else None
            alerts_scheduled += schedule_alerts(
                fresh_sides,
                message_type=notification_message_type,
                delivery_context=notification_delivery_context,
            )
            schedule_stats = get_last_schedule_stats()
            schedule_stats["message_type"] = notification_message_type
            schedule_stats["delivery_context"] = notification_delivery_context
            schedule_stats["alert_route_selected"] = use_alert_route
            alert_skip_totals["skipped_memory_dedupe"] += int(schedule_stats.get("skipped_memory_dedupe") or 0)
            alert_skip_totals["skipped_shared_dedupe"] += int(schedule_stats.get("skipped_shared_dedupe") or 0)
            alert_skip_totals["skipped_threshold"] += int(schedule_stats.get("skipped_threshold") or 0)
        else:
            schedule_stats = {
                "mode": alert_mode,
                "candidates_seen": candidates_seen,
                "scheduled": 0,
                "skipped_memory_dedupe": 0,
                "skipped_shared_dedupe": 0,
                "skipped_threshold": candidates_seen,
                "skipped_total": candidates_seen,
                "message_type": "none",
                "delivery_context": None,
                "alert_route_selected": False,
            }

        log_event(
            "scheduler.board_drop.scan_completed",
            run_id=run_id,
            straight_sides=result.get("straight_sides"),
            props_sides=result.get("props_sides"),
            featured_games_count=result.get("featured_games_count"),
            game_line_sports=result.get("game_line_sports_scanned"),
            props_events_scanned=result.get("props_events_scanned"),
            discord_alert_schedule=schedule_stats,
            scan_alert_mode=alert_mode,
        )
    except Exception as exc:
        hard_errors = 1
        log_event(
            "scheduler.board_drop.failed",
            level="error",
            run_id=run_id,
            error_class=type(exc).__name__,
            error=str(exc),
        )

    finished = datetime.now(UTC).isoformat()
    autolog_summary = None
    try:
        autolog_summary = await run_longshot_autolog_for_sides(
            db=get_db(),
            run_id=run_id,
            sides=fresh_straight_sides,
        )
    except Exception as exc:
        autolog_summary = {
            "enabled": is_paper_experiment_autolog_enabled(),
            "error": f"{type(exc).__name__}: {exc}",
        }
        log_event(
            "scheduler.board_drop.autolog.failed",
            level="error",
            run_id=run_id,
            error_class=type(exc).__name__,
            error=str(exc),
        )

    if alert_mode == DISCORD_SCAN_ALERT_MODE_TIMED_PING:
        if hard_errors == 0:
            notification_message_type = "alert" if use_alert_route else "heartbeat"
            notification_delivery_context = "scheduled_board_drop" if use_alert_route else None
            board_alert_payload = build_board_drop_alert_payload(
                window_label=scan_window["label"],
                anchor_time_mst=scan_window["anchor_time_mst"],
                result={
                    "props_sides": result.get("props_sides"),
                    "straight_sides": result.get("straight_sides"),
                    "featured_games_count": result.get("featured_games_count"),
                },
            )
            try:
                delivery = await send_discord_webhook(
                    board_alert_payload,
                    message_type=notification_message_type,
                    delivery_context=notification_delivery_context,
                )
                board_alert = {
                    "attempted": True,
                    "delivery_status": delivery.get("delivery_status") if isinstance(delivery, dict) else "delivered",
                    "status_code": delivery.get("status_code") if isinstance(delivery, dict) else None,
                    "route_kind": delivery.get("route_kind") if isinstance(delivery, dict) else None,
                    "webhook_source": delivery.get("webhook_source") if isinstance(delivery, dict) else None,
                    "error": None,
                    "message_type": notification_message_type,
                    "delivery_context": notification_delivery_context,
                    "alert_route_selected": use_alert_route,
                }
            except DiscordDeliveryError as exc:
                board_alert = {
                    "attempted": True,
                    "delivery_status": "failed",
                    "status_code": exc.status_code,
                    "route_kind": exc.route_kind,
                    "webhook_source": exc.webhook_source,
                    "error": str(exc),
                    "message_type": notification_message_type,
                    "delivery_context": notification_delivery_context,
                    "alert_route_selected": use_alert_route,
                }
            except Exception as exc:
                board_alert = {
                    "attempted": True,
                    "delivery_status": "failed_unexpected",
                    "status_code": None,
                    "route_kind": None,
                    "webhook_source": None,
                    "error": f"{type(exc).__name__}: {exc}",
                    "message_type": notification_message_type,
                    "delivery_context": notification_delivery_context,
                    "alert_route_selected": use_alert_route,
                }
        else:
            board_alert = {
                "attempted": False,
                "delivery_status": "skipped_due_to_errors",
                "status_code": None,
                "route_kind": None,
                "webhook_source": None,
                "error": None,
                "message_type": None,
                "delivery_context": None,
                "alert_route_selected": False,
            }
        log_event(
            "scheduler.board_drop.alert",
            run_id=run_id,
            scan_window=scan_window,
            delivery_status=board_alert.get("delivery_status"),
            status_code=board_alert.get("status_code"),
            route_kind=board_alert.get("route_kind"),
            webhook_source=board_alert.get("webhook_source"),
            error=board_alert.get("error"),
        )

    total_sides = int(result.get("straight_sides") or 0) + int(result.get("props_sides") or 0)
    total_events = int(result.get("game_lines_events_fetched") or 0) + int(result.get("props_events_fetched") or 0)
    total_with_both = int(result.get("game_lines_events_with_both_books") or 0) + int(
        result.get("props_events_with_both_books") or 0
    )
    remaining_candidates: list[int] = []
    remaining_fallback: str | None = None
    for raw in (result.get("game_lines_api_requests_remaining"), result.get("props_api_requests_remaining")):
        if raw is None:
            continue
        if remaining_fallback is None:
            remaining_fallback = str(raw)
        try:
            remaining_candidates.append(int(raw))
        except (TypeError, ValueError):
            continue
    min_remaining = str(min(remaining_candidates)) if remaining_candidates else remaining_fallback
    duration_ms = round((time.monotonic() - started_at) * 1000, 2)
    result_summary = dict(result.get("summary") or {})
    if not result_summary:
        result_summary = {
            "straight_sides": int(result.get("straight_sides") or 0),
            "props_sides": int(result.get("props_sides") or 0),
            "featured_games_count": int(result.get("featured_games_count") or 0),
            "game_line_sports_scanned": result.get("game_line_sports_scanned") or [],
            "props_events_scanned": int(result.get("props_events_scanned") or 0),
        }
    result_summary.setdefault("scan_label", scan_window["label"])
    result_summary.setdefault("anchor_time_mst", scan_window["anchor_time_mst"])
    result_summary["duration_ms"] = duration_ms

    log_event(
        "scheduler.board_drop.completed",
        run_id=run_id,
        finished_at=finished + "Z",
        straight_sides=result.get("straight_sides"),
        props_sides=result.get("props_sides"),
        total_sides=total_sides,
        alerts_scheduled=alerts_scheduled,
        alert_skip_totals=alert_skip_totals,
        autolog_summary=autolog_summary,
        scan_window=scan_window,
        scan_alert_mode=alert_mode,
        board_alert=board_alert,
        duration_ms=duration_ms,
    )
    if hard_errors:
        ops_runtime.record_scheduler_heartbeat(
            "scheduled_scan",
            run_id,
            "failure",
            duration_ms=duration_ms,
            error="scheduled board drop failed",
        )
    else:
        ops_runtime.record_scheduler_heartbeat("scheduled_scan", run_id, "success", duration_ms=duration_ms)

    scheduler_status_payload = {
        "kind": "board_drop",
        "source": "scheduler",
        "surface": "board_drop",
        "status": "completed" if hard_errors == 0 else "completed_with_errors",
        "canonical_board_updated": True,
        "run_id": run_id,
        "started_at": started + "Z",
        "finished_at": finished + "Z",
        "duration_ms": duration_ms,
        "board_drop": True,
        "total_sides": total_sides,
        "straight_sides": int(result.get("straight_sides") or 0),
        "props_sides": int(result.get("props_sides") or 0),
        "featured_games_count": int(result.get("featured_games_count") or 0),
        "alerts_scheduled": alerts_scheduled,
        "alert_skip_totals": alert_skip_totals,
        "scan_window": scan_window,
        "scan_alert_mode": alert_mode,
        "board_alert": board_alert,
        "board_alert_attempted": bool(board_alert.get("attempted")),
        "board_alert_delivery_status": board_alert.get("delivery_status"),
        "board_alert_http_status": board_alert.get("status_code"),
        "board_alert_error": board_alert.get("error"),
        "game_line_sports_scanned": result.get("game_line_sports_scanned") or [],
        "props_events_scanned": int(result.get("props_events_scanned") or 0),
        "result": result_summary,
        "hard_errors": hard_errors,
        "captured_at": finished + "Z",
        "autolog_summary": autolog_summary,
    }
    ops_runtime.set_ops_status("last_scheduler_scan", scheduler_status_payload)
    ops_runtime.set_ops_status("last_board_refresh", scheduler_status_payload)
    ops_runtime.persist_ops_job_run(
        job_kind="scheduled_board_drop",
        source="scheduler",
        status="completed" if hard_errors == 0 else "completed_with_errors",
        run_id=run_id,
        scan_session_id=run_id,
        surface="board_drop",
        scan_scope="all",
        requested_sport="board",
        captured_at=finished + "Z",
        started_at=started + "Z",
        finished_at=finished + "Z",
        duration_ms=duration_ms,
        events_fetched=total_events,
        events_with_both_books=total_with_both,
        total_sides=total_sides,
        alerts_scheduled=alerts_scheduled,
        hard_errors=hard_errors,
        api_requests_remaining=min_remaining,
        meta={
            "autolog_summary": autolog_summary,
            "alert_skip_totals": alert_skip_totals,
            "scan_window": scan_window,
            "scan_alert_mode": alert_mode,
            "board_alert": board_alert,
            "board_alert_attempted": bool(board_alert.get("attempted")),
            "board_alert_delivery_status": board_alert.get("delivery_status"),
            "board_alert_http_status": board_alert.get("status_code"),
            "board_alert_error": board_alert.get("error"),
            "result_summary": result_summary,
        },
    )

    if (
        alert_mode == DISCORD_SCAN_ALERT_MODE_EDGE_LIVE
        and os.getenv("DISCORD_AUTO_SETTLE_HEARTBEAT") == "1"
        and alerts_scheduled == 0
    ):
        payload = {
            "embeds": [
                {
                    "title": "Scheduled board drop complete (no alerts)",
                    "description": "The scheduled board drop ran successfully but found no qualifying lines to alert on.",
                    "fields": [
                        {"name": "Started (UTC)", "value": started + "Z", "inline": True},
                        {"name": "Finished (UTC)", "value": finished + "Z", "inline": True},
                        {"name": "Total sides", "value": str(total_sides), "inline": True},
                        {"name": "Alerts scheduled", "value": str(alerts_scheduled), "inline": True},
                    ],
                }
            ]
        }
        asyncio.create_task(send_discord_webhook(payload, message_type="heartbeat"))


async def run_scheduled_scan_job() -> None:
    await run_scheduled_board_drop_job()


async def run_early_look_scan_job() -> None:
    await run_scheduled_board_drop_job()


async def start_scheduler(app=None) -> None:
    if app is not None:
        ops_runtime.configure_app(app)
    if os.getenv("TESTING") == "1":
        return
    if os.getenv("ENABLE_SCHEDULER") != "1":
        return
    if (os.getenv("APP_ROLE") or "").strip().lower() == "api":
        return

    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    ops_runtime.init_scheduler_heartbeats()
    scheduler = AsyncIOScheduler()
    scheduler.add_job(run_jit_clv_snatcher_job, IntervalTrigger(minutes=5))

    auto_settle_trigger = (
        CronTrigger(hour="4,22", minute=0, timezone=PHOENIX_TZ)
        if PHOENIX_TZ is not None
        else CronTrigger(hour="4,22", minute=0)
    )
    scheduler.add_job(
        run_auto_settler_job,
        auto_settle_trigger,
        misfire_grace_time=60 * 60,
        coalesce=True,
    )
    if PHOENIX_TZ is not None:
        scheduled_alert_times: set[tuple[int, int]] = {
            (hour, minute) for hour, minute, _label in SCHEDULED_SCAN_WINDOWS_MST
        }
        scheduled_scan_times: list[tuple[int, int]] = list(scheduled_alert_times)
        temp_scan_time = parse_hhmm(os.getenv(SCHEDULED_SCAN_TEMP_TIME_ENV))
        if temp_scan_time is not None and temp_scan_time not in scheduled_scan_times:
            scheduled_scan_times.append(temp_scan_time)

        for hour, minute in scheduled_scan_times:
            scheduler.add_job(
                run_scheduled_board_drop_job,
                CronTrigger(hour=hour, minute=minute, timezone=PHOENIX_TZ),
                kwargs={"alert_delivery_allowed": (hour, minute) in scheduled_alert_times},
                misfire_grace_time=scheduled_board_drop_alert_grace_minutes() * 60,
                coalesce=True,
            )
    else:
        print("[Scheduler] Phoenix timezone unavailable; skipping scheduled board drop jobs.")

    scheduler.start()
    app_state = ops_runtime.get_app().state
    app_state.scheduler_started_at = utc_now_iso()
    jobs_count = len(scheduler.get_jobs()) if hasattr(scheduler, "get_jobs") else len(getattr(scheduler, "jobs", []))
    log_event("scheduler.started", jobs=jobs_count)
    app_state.scheduler = scheduler


async def stop_scheduler(app=None) -> None:
    if app is not None:
        ops_runtime.configure_app(app)
    try:
        scheduler = getattr(ops_runtime.get_app().state, "scheduler", None)
    except Exception:
        scheduler = None
    if scheduler:
        try:
            scheduler.shutdown(wait=False)
            log_event("scheduler.stopped")
        except Exception as exc:
            log_event(
                "scheduler.stop_failed",
                level="error",
                error_class=type(exc).__name__,
                error=str(exc),
            )
