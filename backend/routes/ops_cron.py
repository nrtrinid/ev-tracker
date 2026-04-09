import asyncio
import os
import time
from datetime import datetime, UTC
from typing import Any, Callable

import httpx
from fastapi import APIRouter, Depends, HTTPException, Header, Query

from dependencies import require_ops_token
from models import (
    ModelCalibrationSummaryResponse,
    PickEmResearchSummaryResponse,
    ResearchOpportunitySummaryResponse,
)


router = APIRouter()


def _raise_if_delivery_disabled(delivery: Any, *, run_id: str, fallback_message_type: str) -> None:
    if not isinstance(delivery, dict):
        return
    if delivery.get("delivery_status") != "disabled_no_webhook":
        return
    raise HTTPException(
        status_code=503,
        detail={
            "ok": False,
            "error": "discord_webhook_not_configured",
            "message_type": delivery.get("message_type") or fallback_message_type,
            "route_kind": delivery.get("route_kind"),
            "webhook_source": delivery.get("webhook_source"),
            "run_id": run_id,
        },
    )


async def cron_run_scan_impl(
    x_cron_token: str | None,
    *,
    require_valid_cron_token: Callable[[str | None], None],
    new_run_id: Callable[[str], str],
    log_event: Callable[..., None],
    set_ops_status: Callable[[str, dict], None],
    persist_ops_job_run: Callable[..., None],
    apply_fresh_scan_followups: Callable[[dict[str, Any]], Any] | None = None,
    run_id_prefix: str = "cron_scan",
    log_prefix: str = "cron.scan",
    scan_source: str = "cron_scan",
    ops_status_key: str = "last_cron_scan",
) -> dict[str, Any]:
    """Cron-triggered scan runner implementation used by the API route wrapper."""
    require_valid_cron_token(x_cron_token)

    run_id = new_run_id(run_id_prefix)
    started_clock = time.monotonic()
    log_event(f"{log_prefix}.started", run_id=run_id)

    from services.odds_api import append_scan_activity, get_cached_or_scan, SUPPORTED_SPORTS
    from services.discord_alerts import get_last_schedule_stats, schedule_alerts

    started = datetime.now(UTC).isoformat() + "Z"
    scanned = []
    errors: list[dict] = []
    total_sides = 0
    alerts_scheduled = 0
    total_events = 0
    total_with_both = 0
    min_remaining: str | None = None
    alert_skip_totals = {
        "skipped_memory_dedupe": 0,
        "skipped_shared_dedupe": 0,
        "skipped_threshold": 0,
    }

    for sport_key in SUPPORTED_SPORTS:
        sport_started_at = time.monotonic()
        try:
            result = await get_cached_or_scan(sport_key, source=scan_source)
            scan_duration_ms = round((time.monotonic() - sport_started_at) * 1000, 2)
            sides = result.get("sides") or []
            append_scan_activity(
                scan_session_id=run_id,
                source=scan_source,
                surface="straight_bets",
                scan_scope="all",
                requested_sport=None,
                sport=sport_key,
                actor_label=None,
                run_id=run_id,
                cache_hit=bool(result.get("cache_hit")),
                outbound_call_made=not bool(result.get("cache_hit")),
                duration_ms=scan_duration_ms,
                events_fetched=int(result.get("events_fetched") or 0),
                events_with_both_books=int(result.get("events_with_both_books") or 0),
                sides_count=len(sides),
                api_requests_remaining=result.get("api_requests_remaining"),
                status_code=200,
                error_type=None,
                error_message=None,
            )
            if apply_fresh_scan_followups is not None:
                followup_result = apply_fresh_scan_followups(result)
                if asyncio.iscoroutine(followup_result):
                    await followup_result
            scanned.append(
                {
                    "sport": sport_key,
                    "sides": len(sides),
                    "events_fetched": result.get("events_fetched"),
                    "events_with_both_books": result.get("events_with_both_books"),
                    "api_requests_remaining": result.get("api_requests_remaining"),
                }
            )
            total_sides += len(sides)
            total_events += int(result.get("events_fetched") or 0)
            total_with_both += int(result.get("events_with_both_books") or 0)
            remaining = result.get("api_requests_remaining")
            if remaining is not None:
                try:
                    remaining_int = int(remaining)
                    min_remaining = (
                        str(remaining_int)
                        if min_remaining is None
                        else str(min(remaining_int, int(min_remaining)))
                    )
                except (TypeError, ValueError):
                    min_remaining = str(remaining)
            alerts_scheduled += schedule_alerts(sides)
            schedule_stats = get_last_schedule_stats()
            alert_skip_totals["skipped_memory_dedupe"] += int(schedule_stats.get("skipped_memory_dedupe") or 0)
            alert_skip_totals["skipped_shared_dedupe"] += int(schedule_stats.get("skipped_shared_dedupe") or 0)
            alert_skip_totals["skipped_threshold"] += int(schedule_stats.get("skipped_threshold") or 0)
            log_event(
                f"{log_prefix}.alert_schedule",
                run_id=run_id,
                sport=sport_key,
                discord_alert_schedule=schedule_stats,
            )
        except httpx.HTTPStatusError as e:
            scan_duration_ms = round((time.monotonic() - sport_started_at) * 1000, 2)
            status = e.response.status_code if e.response is not None else None
            remaining = None
            if e.response is not None:
                remaining = e.response.headers.get("x-requests-remaining") or e.response.headers.get("x-request-remaining")
            append_scan_activity(
                scan_session_id=run_id,
                source=scan_source,
                surface="straight_bets",
                scan_scope="all",
                requested_sport=None,
                sport=sport_key,
                actor_label=None,
                run_id=run_id,
                cache_hit=False,
                outbound_call_made=True,
                duration_ms=scan_duration_ms,
                events_fetched=0,
                events_with_both_books=0,
                sides_count=0,
                api_requests_remaining=remaining,
                status_code=status,
                error_type=type(e).__name__,
                error_message=str(e),
            )
            if status == 404:
                errors.append({"sport": sport_key, "status": 404, "error": "no odds"})
                log_event(f"{log_prefix}.sport_skipped", run_id=run_id, sport=sport_key, status=404, reason="no odds")
                continue
            errors.append({"sport": sport_key, "status": status, "error": str(e)})
            log_event(
                f"{log_prefix}.sport_failed",
                level="error",
                run_id=run_id,
                sport=sport_key,
                status=status,
                error_class=type(e).__name__,
                error=str(e),
            )
        except Exception as e:
            scan_duration_ms = round((time.monotonic() - sport_started_at) * 1000, 2)
            append_scan_activity(
                scan_session_id=run_id,
                source=scan_source,
                surface="straight_bets",
                scan_scope="all",
                requested_sport=None,
                sport=sport_key,
                actor_label=None,
                run_id=run_id,
                cache_hit=False,
                outbound_call_made=False,
                duration_ms=scan_duration_ms,
                events_fetched=0,
                events_with_both_books=0,
                sides_count=0,
                api_requests_remaining=None,
                status_code=None,
                error_type=type(e).__name__,
                error_message=str(e),
            )
            errors.append({"sport": sport_key, "error": str(e)})
            log_event(
                f"{log_prefix}.sport_failed",
                level="error",
                run_id=run_id,
                sport=sport_key,
                error_class=type(e).__name__,
                error=str(e),
            )

    finished = datetime.now(UTC).isoformat() + "Z"
    duration_ms = round((time.monotonic() - started_clock) * 1000, 2)
    log_event(
        f"{log_prefix}.completed",
        run_id=run_id,
        total_sides=total_sides,
        alerts_scheduled=alerts_scheduled,
        alert_skip_totals=alert_skip_totals,
        error_count=len(errors),
        duration_ms=duration_ms,
    )

    set_ops_status(
        ops_status_key,
        {
            "run_id": run_id,
            "started_at": started,
            "finished_at": finished,
            "duration_ms": duration_ms,
            "total_sides": total_sides,
            "alerts_scheduled": alerts_scheduled,
            "alert_skip_totals": alert_skip_totals,
            "error_count": len(errors),
            "errors": errors,
            "captured_at": finished,
        },
    )
    persist_ops_job_run(
        job_kind="ops_trigger_scan" if ops_status_key == "last_ops_trigger_scan" else "scheduled_scan",
        source="ops_trigger" if ops_status_key == "last_ops_trigger_scan" else "scheduler",
        status="completed" if not errors else "completed_with_errors",
        run_id=run_id,
        scan_session_id=run_id,
        surface="straight_bets",
        scan_scope="all",
        requested_sport="all",
        captured_at=finished,
        started_at=started,
        finished_at=finished,
        duration_ms=duration_ms,
        events_fetched=total_events,
        events_with_both_books=total_with_both,
        total_sides=total_sides,
        alerts_scheduled=alerts_scheduled,
        api_requests_remaining=min_remaining,
        hard_errors=len(errors) if ops_status_key != "last_ops_trigger_scan" else None,
        error_count=len(errors),
        errors=errors,
        meta={"alert_skip_totals": alert_skip_totals},
    )

    if os.getenv("DISCORD_AUTO_SETTLE_HEARTBEAT") == "1" and alerts_scheduled == 0:
        from services.discord_alerts import send_discord_webhook

        payload = {
            "embeds": [
                {
                    "title": "Scan run complete (no alerts)",
                    "description": "The scheduled scan ran successfully but found no qualifying lines to alert on.",
                    "fields": [
                        {"name": "Started (UTC)", "value": started, "inline": True},
                        {"name": "Finished (UTC)", "value": finished, "inline": True},
                        {"name": "Total sides", "value": str(total_sides), "inline": True},
                        {"name": "Alerts scheduled", "value": str(alerts_scheduled), "inline": True},
                    ],
                }
            ]
        }
        asyncio.create_task(send_discord_webhook(payload, message_type="heartbeat"))

    return {
        "ok": True,
        "run_id": run_id,
        "started_at": started,
        "finished_at": finished,
        "duration_ms": duration_ms,
        "board_drop": True,
        "result": {
            "props_sides": total_sides,
            "events_fetched": total_events,
            "events_with_both_books": total_with_both,
        },
        "sports_scanned": scanned,
        "errors": errors,
        "total_sides": total_sides,
        "alerts_scheduled": alerts_scheduled,
        "alert_skip_totals": alert_skip_totals,
    }


async def cron_run_auto_settle_impl(
    x_cron_token: str | None,
    *,
    require_valid_cron_token: Callable[[str | None], None],
    new_run_id: Callable[[str], str],
    log_event: Callable[..., None],
    set_ops_status: Callable[[str, dict], None],
    persist_ops_job_run: Callable[..., None],
    get_db: Callable[[], Any],
    run_id_prefix: str = "cron_auto_settle",
    log_prefix: str = "cron.auto_settle",
    auto_settle_source: str = "auto_settle_cron",
    ops_status_source: str = "cron",
) -> dict[str, Any]:
    """Cron-triggered auto-settle runner implementation used by the API route wrapper."""
    require_valid_cron_token(x_cron_token)

    run_id = new_run_id(run_id_prefix)
    started_clock = time.monotonic()
    log_event(f"{log_prefix}.started", run_id=run_id)

    from services.odds_api import get_last_auto_settler_summary

    db = get_db()
    started = datetime.now(UTC).isoformat() + "Z"
    try:
        from services.odds_api import run_auto_settler

        settled = await run_auto_settler(db, source=auto_settle_source)
        log_event(f"{log_prefix}.completed", run_id=run_id, settled=settled)
    except Exception as e:
        log_event(
            f"{log_prefix}.failed",
            level="error",
            run_id=run_id,
            error_class=type(e).__name__,
            error=str(e),
            duration_ms=round((time.monotonic() - started_clock) * 1000, 2),
        )
        raise HTTPException(status_code=502, detail=f"Auto-settler error: {e}")
    finally:
        finished = datetime.now(UTC).isoformat() + "Z"

    duration_ms = round((time.monotonic() - started_clock) * 1000, 2)

    set_ops_status(
        "last_auto_settle",
        {
            "source": ops_status_source,
            "run_id": run_id,
            "started_at": started,
            "finished_at": finished,
            "duration_ms": duration_ms,
            "settled": settled,
            "captured_at": finished,
        },
    )
    summary = get_last_auto_settler_summary()
    if summary:
        set_ops_status("last_auto_settle_summary", summary)
    persist_ops_job_run(
        job_kind="auto_settle",
        source=ops_status_source,
        status="completed",
        run_id=run_id,
        captured_at=finished,
        started_at=started,
        finished_at=finished,
        duration_ms=duration_ms,
        settled=settled,
        skipped_totals=summary.get("skipped_totals") if isinstance(summary, dict) else None,
        meta={"sports": summary.get("sports")} if isinstance(summary, dict) and isinstance(summary.get("sports"), list) else None,
    )

    if os.getenv("DISCORD_AUTO_SETTLE_HEARTBEAT") == "1":
        from services.discord_alerts import send_discord_webhook

        payload = {
            "embeds": [
                {
                    "title": "Auto-settle run complete",
                    "description": f"Graded **{settled}** bet(s).",
                    "fields": [
                        {"name": "Started (UTC)", "value": started, "inline": True},
                        {"name": "Finished (UTC)", "value": finished, "inline": True},
                    ],
                }
            ]
        }
        asyncio.create_task(send_discord_webhook(payload, message_type="heartbeat"))

    return {
        "ok": True,
        "run_id": run_id,
        "started_at": started,
        "finished_at": finished,
        "duration_ms": duration_ms,
        "settled": settled,
    }


def ops_status_impl(
    x_cron_token: str | None,
    *,
    require_valid_cron_token: Callable[[str | None], None],
    runtime_state: Callable[[], dict],
    check_db_ready: Callable[[], tuple[bool, str | None]],
    check_scheduler_freshness: Callable[[bool], tuple[bool, dict]],
    utc_now_iso: Callable[[], str],
    get_db: Callable[[], Any],
    retry_supabase: Callable[[Callable[[], Any]], Any],
    log_event: Callable[..., None],
    get_ops_status: Callable[[], dict],
) -> dict[str, Any]:
    """Protected operator status implementation used by the API route wrapper."""
    require_valid_cron_token(x_cron_token)

    runtime = runtime_state()
    db_ok, db_error = check_db_ready()
    scheduler_fresh_ok, scheduler_freshness = check_scheduler_freshness(runtime["scheduler_expected"])
    from services.odds_api import get_odds_api_activity_snapshot
    from services.ops_history import load_ops_status_snapshot

    fallback_ops = get_ops_status()
    odds_api_activity = get_odds_api_activity_snapshot()
    try:
        db = get_db()
    except Exception:
        db = None
    ops = load_ops_status_snapshot(
        db=db,
        retry_supabase=retry_supabase,
        log_event=log_event,
        fallback_ops_status=fallback_ops,
        fallback_odds_api_activity=odds_api_activity,
    )

    return {
        "timestamp": utc_now_iso(),
        "runtime": runtime,
        "checks": {
            "db_connectivity": db_ok,
            "scheduler_freshness": scheduler_fresh_ok,
        },
        "db_error": db_error,
        "scheduler_freshness": scheduler_freshness,
        "ops": ops,
    }


def ops_research_opportunities_summary_impl(
    x_cron_token: str | None,
    *,
    require_valid_cron_token: Callable[[str | None], None],
    get_db: Callable[[], Any],
    get_summary: Callable[..., ResearchOpportunitySummaryResponse],
    scope: str | None = None,
) -> ResearchOpportunitySummaryResponse:
    """Protected research summary implementation used by the API route wrapper."""
    require_valid_cron_token(x_cron_token)
    normalized_scope = (scope or "").strip().lower()
    if not normalized_scope or normalized_scope == "all":
        return get_summary(get_db())
    return get_summary(get_db(), scope=normalized_scope)


def ops_model_calibration_summary_impl(
    x_cron_token: str | None,
    *,
    require_valid_cron_token: Callable[[str | None], None],
    get_db: Callable[[], Any],
    get_summary: Callable[[Any], ModelCalibrationSummaryResponse],
) -> ModelCalibrationSummaryResponse:
    """Protected model-calibration summary implementation used by the API route wrapper."""
    require_valid_cron_token(x_cron_token)
    return get_summary(get_db())


def ops_pickem_research_summary_impl(
    x_cron_token: str | None,
    *,
    require_valid_cron_token: Callable[[str | None], None],
    get_db: Callable[[], Any],
    get_summary: Callable[[Any], PickEmResearchSummaryResponse],
) -> PickEmResearchSummaryResponse:
    """Protected pick'em-research summary implementation used by the API route wrapper."""
    require_valid_cron_token(x_cron_token)
    return get_summary(get_db())


def ops_analytics_summary_impl(
    x_cron_token: str | None,
    *,
    require_valid_cron_token: Callable[[str | None], None],
    get_db: Callable[[], Any],
    get_summary: Callable[..., dict[str, Any]],
    retry_supabase: Callable[[Callable[[], Any]], Any] | None,
    window_days: int,
) -> dict[str, Any]:
    """Protected analytics summary implementation used by the API route wrapper."""
    require_valid_cron_token(x_cron_token)
    return get_summary(
        db=get_db(),
        window_days=window_days,
        retry_supabase=retry_supabase,
    )


def ops_analytics_users_impl(
    x_cron_token: str | None,
    *,
    require_valid_cron_token: Callable[[str | None], None],
    get_db: Callable[[], Any],
    get_summary: Callable[..., dict[str, Any]],
    retry_supabase: Callable[[Callable[[], Any]], Any] | None,
    window_days: int,
    max_users: int,
    timeline_limit: int,
) -> dict[str, Any]:
    """Protected analytics per-user drilldown implementation used by the API route wrapper."""
    require_valid_cron_token(x_cron_token)
    return get_summary(
        db=get_db(),
        window_days=window_days,
        max_users=max_users,
        timeline_limit=timeline_limit,
        retry_supabase=retry_supabase,
    )


def ops_clv_debug_impl(
    x_cron_token: str | None,
    *,
    require_valid_cron_token: Callable[[str | None], None],
    get_db: Callable[[], Any],
    retry_supabase: Callable[[Callable[[], Any]], Any],
    load_snapshot: Callable[..., dict[str, Any]],
    load_scheduler_job_snapshot: Callable[..., dict[str, Any]],
    load_recent_clv_job_runs: Callable[..., list[dict[str, Any]]],
    utc_now_iso: Callable[[], str],
) -> dict[str, Any]:
    require_valid_cron_token(x_cron_token)
    return load_snapshot(
        get_db(),
        retry_supabase=retry_supabase,
        load_scheduler_job_snapshot=load_scheduler_job_snapshot,
        load_recent_clv_job_runs=load_recent_clv_job_runs,
        utc_now_iso=utc_now_iso,
    )


async def cron_run_clv_daily_impl(
    x_cron_token: str | None,
    *,
    require_valid_cron_token: Callable[[str | None], None],
    new_run_id: Callable[[str], str],
    log_event: Callable[..., None],
    set_ops_status: Callable[[str, dict], None],
    persist_ops_job_run: Callable[..., None],
    get_db: Callable[[], Any],
    run_id_prefix: str = "cron_clv_daily",
    log_prefix: str = "cron.clv_daily",
    ops_status_source: str = "cron",
) -> dict[str, Any]:
    require_valid_cron_token(x_cron_token)

    run_id = new_run_id(run_id_prefix)
    started_clock = time.monotonic()
    log_event(f"{log_prefix}.started", run_id=run_id)

    from services.odds_api import fetch_clv_for_pending_bets

    db = get_db()
    started = datetime.now(UTC).isoformat() + "Z"
    summary: dict[str, Any] | None = None
    try:
        summary = await fetch_clv_for_pending_bets(db, include_summary=True)
        log_event(
            f"{log_prefix}.completed",
            run_id=run_id,
            updated=int((summary or {}).get("close_updated", 0)),
            summary=summary,
        )
    except Exception as e:
        log_event(
            f"{log_prefix}.failed",
            level="error",
            run_id=run_id,
            error_class=type(e).__name__,
            error=str(e),
            duration_ms=round((time.monotonic() - started_clock) * 1000, 2),
        )
        raise HTTPException(status_code=502, detail=f"Daily CLV safety-net error: {e}")
    finally:
        finished = datetime.now(UTC).isoformat() + "Z"

    duration_ms = round((time.monotonic() - started_clock) * 1000, 2)
    updated = int((summary or {}).get("close_updated", 0))
    set_ops_status(
        "last_clv_daily",
        {
            "source": ops_status_source,
            "run_id": run_id,
            "started_at": started,
            "finished_at": finished,
            "duration_ms": duration_ms,
            "updated": updated,
            "captured_at": finished,
            "summary": summary,
        },
    )
    persist_ops_job_run(
        job_kind="clv_daily",
        source=ops_status_source,
        status="completed",
        run_id=run_id,
        captured_at=finished,
        started_at=started,
        finished_at=finished,
        duration_ms=duration_ms,
        meta=summary or {"updated": updated},
    )

    return {
        "ok": True,
        "run_id": run_id,
        "started_at": started,
        "finished_at": finished,
        "duration_ms": duration_ms,
        "updated": updated,
        "summary": summary,
    }


async def ops_replay_recent_clv_impl(
    x_cron_token: str | None,
    *,
    require_valid_cron_token: Callable[[str | None], None],
    new_run_id: Callable[[str], str],
    log_event: Callable[..., None],
    set_ops_status: Callable[[str, dict], None],
    persist_ops_job_run: Callable[..., None],
    get_db: Callable[[], Any],
    replay_recent_closes: Callable[..., Any],
    lookback_hours: int,
) -> dict[str, Any]:
    require_valid_cron_token(x_cron_token)
    run_id = new_run_id("ops_clv_replay")
    started = datetime.now(UTC).isoformat() + "Z"
    started_clock = time.monotonic()
    log_event("ops.trigger.clv_replay.started", run_id=run_id, lookback_hours=lookback_hours)
    summary = await replay_recent_closes(get_db(), lookback_hours=lookback_hours)
    finished = datetime.now(UTC).isoformat() + "Z"
    duration_ms = round((time.monotonic() - started_clock) * 1000, 2)
    set_ops_status(
        "last_clv_replay",
        {
            "source": "ops",
            "run_id": run_id,
            "started_at": started,
            "finished_at": finished,
            "duration_ms": duration_ms,
            "updated": int((summary or {}).get("close_updated", 0)),
            "captured_at": finished,
            "summary": summary,
        },
    )
    persist_ops_job_run(
        job_kind="clv_replay",
        source="ops",
        status="completed",
        run_id=run_id,
        captured_at=finished,
        started_at=started,
        finished_at=finished,
        duration_ms=duration_ms,
        meta=summary,
    )
    log_event("ops.trigger.clv_replay.completed", run_id=run_id, duration_ms=duration_ms, summary=summary)
    return summary


async def cron_test_discord_impl(
    x_cron_token: str | None,
    *,
    require_valid_cron_token: Callable[[str | None], None],
    new_run_id: Callable[[str], str],
    log_event: Callable[..., None],
    run_id_prefix: str = "cron_discord_test",
    log_prefix: str = "cron.discord_test",
) -> dict[str, Any]:
    """Send a test Discord message implementation used by the API route wrapper."""
    require_valid_cron_token(x_cron_token)

    run_id = new_run_id(run_id_prefix)
    started_at = time.monotonic()
    log_event(f"{log_prefix}.started", run_id=run_id)

    from services.discord_alerts import send_discord_webhook

    payload = {
        "embeds": [
            {
                "title": "Webhook test",
                "description": "If you can read this, DISCORD_WEBHOOK_URL is working.",
                "fields": [
                    {"name": "Server time (UTC)", "value": datetime.now(UTC).isoformat() + "Z", "inline": False},
                ],
            }
        ]
    }

    try:
        delivery = await send_discord_webhook(payload, message_type="test")
        _raise_if_delivery_disabled(delivery, run_id=run_id, fallback_message_type="test")
    except TypeError as exc:
        if "message_type" not in str(exc):
            raise
        delivery = await send_discord_webhook(payload)
        _raise_if_delivery_disabled(delivery, run_id=run_id, fallback_message_type="test")
    except HTTPException:
        raise
    except Exception as exc:
        from services.discord_alerts import DiscordDeliveryError

        if isinstance(exc, DiscordDeliveryError):
            raise HTTPException(
                status_code=502,
                detail={
                    "ok": False,
                    "error": "discord_delivery_failed",
                    "message_type": exc.message_type,
                    "status_code": exc.status_code,
                    "message": str(exc),
                    "response_text": exc.response_text,
                    "run_id": run_id,
                },
            ) from exc
        raise HTTPException(
            status_code=502,
            detail={
                "ok": False,
                "error": "discord_delivery_failed",
                "message_type": "test",
                "message": str(exc),
                "run_id": run_id,
            },
        ) from exc
    log_event(
        f"{log_prefix}.completed",
        run_id=run_id,
        duration_ms=round((time.monotonic() - started_at) * 1000, 2),
    )
    return {
        "ok": True,
        "scheduled": True,
        "run_id": run_id,
        "delivery_status": delivery.get("delivery_status") if isinstance(delivery, dict) else None,
    }


async def cron_test_discord_alert_impl(
    x_cron_token: str | None,
    *,
    require_valid_cron_token: Callable[[str | None], None],
    new_run_id: Callable[[str], str],
    log_event: Callable[..., None],
    run_id_prefix: str = "cron_discord_alert_test",
    log_prefix: str = "cron.discord_alert_test",
) -> dict[str, Any]:
    """Send a test message to the alert webhook (DISCORD_ALERT_WEBHOOK_URL)."""
    require_valid_cron_token(x_cron_token)

    run_id = new_run_id(run_id_prefix)
    started_at = time.monotonic()
    log_event(f"{log_prefix}.started", run_id=run_id)

    from services.discord_alerts import send_discord_webhook

    payload = {
        "embeds": [
            {
                "title": "Alert Webhook Test",
                "description": "If you can read this, DISCORD_ALERT_WEBHOOK_URL is working.",
                "fields": [
                    {"name": "Server time (UTC)", "value": datetime.now(UTC).isoformat() + "Z", "inline": False},
                ],
            }
        ]
    }

    try:
        delivery = await send_discord_webhook(payload, message_type="alert")
        _raise_if_delivery_disabled(delivery, run_id=run_id, fallback_message_type="alert")
    except TypeError as exc:
        if "message_type" not in str(exc):
            raise
        delivery = await send_discord_webhook(payload)
        _raise_if_delivery_disabled(delivery, run_id=run_id, fallback_message_type="alert")
    except HTTPException:
        raise
    except Exception as exc:
        from services.discord_alerts import DiscordDeliveryError

        if isinstance(exc, DiscordDeliveryError):
            raise HTTPException(
                status_code=502,
                detail={
                    "ok": False,
                    "error": "discord_delivery_failed",
                    "message_type": exc.message_type,
                    "status_code": exc.status_code,
                    "message": str(exc),
                    "response_text": exc.response_text,
                    "run_id": run_id,
                },
            ) from exc
        raise HTTPException(
            status_code=502,
            detail={
                "ok": False,
                "error": "discord_delivery_failed",
                "message_type": "alert",
                "message": str(exc),
                "run_id": run_id,
            },
        ) from exc
    log_event(
        f"{log_prefix}.completed",
        run_id=run_id,
        duration_ms=round((time.monotonic() - started_at) * 1000, 2),
    )
    return {
        "ok": True,
        "scheduled": True,
        "run_id": run_id,
        "delivery_status": delivery.get("delivery_status") if isinstance(delivery, dict) else None,
    }


@router.post("/api/ops/trigger/scan")
async def ops_trigger_scan(
    x_ops_token: str | None = Header(default=None, alias="X-Ops-Token"),
    x_cron_token: str | None = Header(default=None, alias="X-Cron-Token"),
    _auth: None = Depends(require_ops_token),
):
    import main

    return await cron_run_scan_impl(
        x_cron_token=x_ops_token or x_cron_token,
        require_valid_cron_token=lambda token: main._require_ops_token(token, None),
        new_run_id=main._new_run_id,
        log_event=main._log_event,
        set_ops_status=main._set_ops_status,
        persist_ops_job_run=main._persist_ops_job_run,
        apply_fresh_scan_followups=lambda result: main._apply_fresh_straight_scan_followups(
            result,
            source="ops_trigger_scan",
        ),
        run_id_prefix="ops_scan",
        log_prefix="ops.trigger.scan",
        scan_source="ops_trigger_scan",
        ops_status_key="last_ops_trigger_scan",
    )


@router.post("/api/ops/trigger/auto-settle")
async def ops_trigger_auto_settle(
    x_ops_token: str | None = Header(default=None, alias="X-Ops-Token"),
    x_cron_token: str | None = Header(default=None, alias="X-Cron-Token"),
    _auth: None = Depends(require_ops_token),
):
    import main

    return await cron_run_auto_settle_impl(
        x_cron_token=x_ops_token or x_cron_token,
        require_valid_cron_token=lambda token: main._require_ops_token(token, None),
        new_run_id=main._new_run_id,
        log_event=main._log_event,
        set_ops_status=main._set_ops_status,
        persist_ops_job_run=main._persist_ops_job_run,
        get_db=main.get_db,
        run_id_prefix="ops_auto_settle",
        log_prefix="ops.trigger.auto_settle",
        auto_settle_source="auto_settle_ops_trigger",
        ops_status_source="ops_trigger",
    )


@router.get("/api/ops/status")
def ops_status(
    x_ops_token: str | None = Header(default=None, alias="X-Ops-Token"),
    x_cron_token: str | None = Header(default=None, alias="X-Cron-Token"),
    _auth: None = Depends(require_ops_token),
):
    import main

    return ops_status_impl(
        x_cron_token=x_ops_token or x_cron_token,
        require_valid_cron_token=lambda token: main._require_ops_token(token, None),
        runtime_state=main._runtime_state,
        check_db_ready=main._check_db_ready,
        check_scheduler_freshness=main._check_scheduler_freshness,
        utc_now_iso=main._utc_now_iso,
        get_db=main.get_db,
        retry_supabase=main._retry_supabase,
        log_event=main._log_event,
        get_ops_status=lambda: getattr(main.app.state, "ops_status", {}),
    )


@router.get("/api/ops/research-opportunities/summary", response_model=ResearchOpportunitySummaryResponse)
def ops_research_opportunities_summary(
    scope: str = Query(default="all"),
    x_ops_token: str | None = Header(default=None, alias="X-Ops-Token"),
    x_cron_token: str | None = Header(default=None, alias="X-Cron-Token"),
    _auth: None = Depends(require_ops_token),
):
    import main
    from services.research_opportunities import get_research_opportunities_summary

    return ops_research_opportunities_summary_impl(
        x_cron_token=x_ops_token or x_cron_token,
        require_valid_cron_token=lambda token: main._require_ops_token(token, None),
        get_db=main.get_db,
        get_summary=get_research_opportunities_summary,
        scope=scope,
    )


@router.get("/api/ops/model-calibration/summary", response_model=ModelCalibrationSummaryResponse)
def ops_model_calibration_summary(
    x_ops_token: str | None = Header(default=None, alias="X-Ops-Token"),
    x_cron_token: str | None = Header(default=None, alias="X-Cron-Token"),
    _auth: None = Depends(require_ops_token),
):
    import main
    from services.model_calibration import get_model_calibration_summary

    return ops_model_calibration_summary_impl(
        x_cron_token=x_ops_token or x_cron_token,
        require_valid_cron_token=lambda token: main._require_ops_token(token, None),
        get_db=main.get_db,
        get_summary=get_model_calibration_summary,
    )


@router.get("/api/ops/pickem-research/summary", response_model=PickEmResearchSummaryResponse)
def ops_pickem_research_summary(
    x_ops_token: str | None = Header(default=None, alias="X-Ops-Token"),
    x_cron_token: str | None = Header(default=None, alias="X-Cron-Token"),
    _auth: None = Depends(require_ops_token),
):
    import main
    from services.pickem_research import get_pickem_research_summary

    return ops_pickem_research_summary_impl(
        x_cron_token=x_ops_token or x_cron_token,
        require_valid_cron_token=lambda token: main._require_ops_token(token, None),
        get_db=main.get_db,
        get_summary=get_pickem_research_summary,
    )


@router.get("/api/ops/clv-debug")
def ops_clv_debug(
    x_ops_token: str | None = Header(default=None, alias="X-Ops-Token"),
    x_cron_token: str | None = Header(default=None, alias="X-Cron-Token"),
    _auth: None = Depends(require_ops_token),
):
    import main
    from services.clv_audit import build_clv_audit_snapshot
    from services.ops_history import load_recent_clv_job_runs, load_scheduler_job_snapshot

    return ops_clv_debug_impl(
        x_cron_token=x_ops_token or x_cron_token,
        require_valid_cron_token=lambda token: main._require_ops_token(token, None),
        get_db=main.get_db,
        retry_supabase=main._retry_supabase,
        load_snapshot=build_clv_audit_snapshot,
        load_scheduler_job_snapshot=load_scheduler_job_snapshot,
        load_recent_clv_job_runs=load_recent_clv_job_runs,
        utc_now_iso=main._utc_now_iso,
    )


@router.post("/api/ops/trigger/clv-daily")
async def ops_trigger_clv_daily(
    x_ops_token: str | None = Header(default=None, alias="X-Ops-Token"),
    x_cron_token: str | None = Header(default=None, alias="X-Cron-Token"),
    _auth: None = Depends(require_ops_token),
):
    import main

    return await cron_run_clv_daily_impl(
        x_cron_token=x_ops_token or x_cron_token,
        require_valid_cron_token=lambda token: main._require_ops_token(token, None),
        new_run_id=main._new_run_id,
        log_event=main._log_event,
        set_ops_status=main._set_ops_status,
        persist_ops_job_run=main._persist_ops_job_run,
        get_db=main.get_db,
        run_id_prefix="ops_clv_daily",
        log_prefix="ops.trigger.clv_daily",
        ops_status_source="ops",
    )


@router.post("/api/ops/trigger/clv-replay")
async def ops_trigger_clv_replay(
    lookback_hours: int = Query(default=8, ge=1, le=24),
    x_ops_token: str | None = Header(default=None, alias="X-Ops-Token"),
    x_cron_token: str | None = Header(default=None, alias="X-Cron-Token"),
    _auth: None = Depends(require_ops_token),
):
    import main
    from services.odds_api import replay_recent_clv_closes

    return await ops_replay_recent_clv_impl(
        x_cron_token=x_ops_token or x_cron_token,
        require_valid_cron_token=lambda token: main._require_ops_token(token, None),
        new_run_id=main._new_run_id,
        log_event=main._log_event,
        set_ops_status=main._set_ops_status,
        persist_ops_job_run=main._persist_ops_job_run,
        get_db=main.get_db,
        replay_recent_closes=replay_recent_clv_closes,
        lookback_hours=lookback_hours,
    )


@router.get("/api/ops/analytics/summary")
def ops_analytics_summary(
    window_days: int = Query(default=7, ge=1, le=30),
    x_ops_token: str | None = Header(default=None, alias="X-Ops-Token"),
    x_cron_token: str | None = Header(default=None, alias="X-Cron-Token"),
    _auth: None = Depends(require_ops_token),
):
    import main
    from services.analytics_reporting import get_weekly_analytics_summary

    return ops_analytics_summary_impl(
        x_cron_token=x_ops_token or x_cron_token,
        require_valid_cron_token=lambda token: main._require_ops_token(token, None),
        get_db=main.get_db,
        get_summary=get_weekly_analytics_summary,
        retry_supabase=main._retry_supabase,
        window_days=window_days,
    )


@router.get("/api/ops/analytics/users")
def ops_analytics_users(
    window_days: int = Query(default=7, ge=1, le=30),
    max_users: int = Query(default=25, ge=1, le=100),
    timeline_limit: int = Query(default=12, ge=1, le=30),
    x_ops_token: str | None = Header(default=None, alias="X-Ops-Token"),
    x_cron_token: str | None = Header(default=None, alias="X-Cron-Token"),
    _auth: None = Depends(require_ops_token),
):
    import main
    from services.analytics_reporting import get_weekly_analytics_user_drilldown

    return ops_analytics_users_impl(
        x_cron_token=x_ops_token or x_cron_token,
        require_valid_cron_token=lambda token: main._require_ops_token(token, None),
        get_db=main.get_db,
        get_summary=get_weekly_analytics_user_drilldown,
        retry_supabase=main._retry_supabase,
        window_days=window_days,
        max_users=max_users,
        timeline_limit=timeline_limit,
    )


@router.post("/api/ops/trigger/test-discord")
async def ops_trigger_test_discord(
    x_ops_token: str | None = Header(default=None, alias="X-Ops-Token"),
    x_cron_token: str | None = Header(default=None, alias="X-Cron-Token"),
    _auth: None = Depends(require_ops_token),
):
    import main

    return await cron_test_discord_impl(
        x_cron_token=x_ops_token or x_cron_token,
        require_valid_cron_token=lambda token: main._require_ops_token(token, None),
        new_run_id=main._new_run_id,
        log_event=main._log_event,
        run_id_prefix="ops_discord_test",
        log_prefix="ops.trigger.discord_test",
    )


@router.post("/api/ops/trigger/test-discord-alert")
async def ops_trigger_test_discord_alert(
    x_ops_token: str | None = Header(default=None, alias="X-Ops-Token"),
    x_cron_token: str | None = Header(default=None, alias="X-Cron-Token"),
    _auth: None = Depends(require_ops_token),
):
    import main

    return await cron_test_discord_alert_impl(
        x_cron_token=x_ops_token or x_cron_token,
        require_valid_cron_token=lambda token: main._require_ops_token(token, None),
        new_run_id=main._new_run_id,
        log_event=main._log_event,
        run_id_prefix="ops_discord_alert_test",
        log_prefix="ops.trigger.discord_alert_test",
    )
