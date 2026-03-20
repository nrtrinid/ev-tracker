import asyncio
import os
import time
from datetime import datetime, UTC
from typing import Any, Callable

import httpx
from fastapi import HTTPException


async def cron_run_scan_impl(
    x_cron_token: str | None,
    *,
    require_valid_cron_token: Callable[[str | None], None],
    new_run_id: Callable[[str], str],
    log_event: Callable[..., None],
    set_ops_status: Callable[[str, dict], None],
) -> dict[str, Any]:
    """Cron-triggered scan runner implementation used by the API route wrapper."""
    require_valid_cron_token(x_cron_token)

    run_id = new_run_id("cron_scan")
    started_clock = time.monotonic()
    log_event("cron.scan.started", run_id=run_id)

    from services.odds_api import get_cached_or_scan, SUPPORTED_SPORTS
    from services.discord_alerts import schedule_alerts

    started = datetime.now(UTC).isoformat() + "Z"
    scanned = []
    errors: list[dict] = []
    total_sides = 0
    alerts_scheduled = 0

    for sport_key in SUPPORTED_SPORTS:
        try:
            result = await get_cached_or_scan(sport_key, source="cron_scan")
            sides = result.get("sides") or []
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
            alerts_scheduled += schedule_alerts(sides)
        except httpx.HTTPStatusError as e:
            status = e.response.status_code if e.response is not None else None
            if status == 404:
                errors.append({"sport": sport_key, "status": 404, "error": "no odds"})
                log_event("cron.scan.sport_skipped", run_id=run_id, sport=sport_key, status=404, reason="no odds")
                continue
            errors.append({"sport": sport_key, "status": status, "error": str(e)})
            log_event(
                "cron.scan.sport_failed",
                level="error",
                run_id=run_id,
                sport=sport_key,
                status=status,
                error_class=type(e).__name__,
                error=str(e),
            )
        except Exception as e:
            errors.append({"sport": sport_key, "error": str(e)})
            log_event(
                "cron.scan.sport_failed",
                level="error",
                run_id=run_id,
                sport=sport_key,
                error_class=type(e).__name__,
                error=str(e),
            )

    finished = datetime.now(UTC).isoformat() + "Z"
    duration_ms = round((time.monotonic() - started_clock) * 1000, 2)
    log_event(
        "cron.scan.completed",
        run_id=run_id,
        total_sides=total_sides,
        alerts_scheduled=alerts_scheduled,
        error_count=len(errors),
        duration_ms=duration_ms,
    )

    set_ops_status(
        "last_cron_scan",
        {
            "run_id": run_id,
            "started_at": started,
            "finished_at": finished,
            "duration_ms": duration_ms,
            "total_sides": total_sides,
            "alerts_scheduled": alerts_scheduled,
            "error_count": len(errors),
            "errors": errors,
        },
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
        asyncio.create_task(send_discord_webhook(payload))

    return {
        "ok": True,
        "run_id": run_id,
        "started_at": started,
        "finished_at": finished,
        "duration_ms": duration_ms,
        "sports_scanned": scanned,
        "errors": errors,
        "total_sides": total_sides,
        "alerts_scheduled": alerts_scheduled,
    }


async def cron_run_auto_settle_impl(
    x_cron_token: str | None,
    *,
    require_valid_cron_token: Callable[[str | None], None],
    new_run_id: Callable[[str], str],
    log_event: Callable[..., None],
    set_ops_status: Callable[[str, dict], None],
    get_db: Callable[[], Any],
) -> dict[str, Any]:
    """Cron-triggered auto-settle runner implementation used by the API route wrapper."""
    require_valid_cron_token(x_cron_token)

    run_id = new_run_id("cron_auto_settle")
    started_clock = time.monotonic()
    log_event("cron.auto_settle.started", run_id=run_id)

    from services.odds_api import get_last_auto_settler_summary

    db = get_db()
    started = datetime.now(UTC).isoformat() + "Z"
    try:
        from services.odds_api import run_auto_settler

        settled = await run_auto_settler(db, source="auto_settle_cron")
        log_event("cron.auto_settle.completed", run_id=run_id, settled=settled)
    except Exception as e:
        log_event(
            "cron.auto_settle.failed",
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
            "source": "cron",
            "run_id": run_id,
            "started_at": started,
            "finished_at": finished,
            "duration_ms": duration_ms,
            "settled": settled,
        },
    )
    summary = get_last_auto_settler_summary()
    if summary:
        set_ops_status("last_auto_settle_summary", summary)

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
        asyncio.create_task(send_discord_webhook(payload))

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
    get_ops_status: Callable[[], dict],
) -> dict[str, Any]:
    """Protected operator status implementation used by the API route wrapper."""
    require_valid_cron_token(x_cron_token)

    runtime = runtime_state()
    db_ok, db_error = check_db_ready()
    scheduler_fresh_ok, scheduler_freshness = check_scheduler_freshness(runtime["scheduler_expected"])
    ops = get_ops_status()
    from services.odds_api import get_odds_api_activity_snapshot

    odds_api_activity = get_odds_api_activity_snapshot()
    if isinstance(ops, dict):
        ops["odds_api_activity"] = odds_api_activity

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


async def cron_test_discord_impl(
    x_cron_token: str | None,
    *,
    require_valid_cron_token: Callable[[str | None], None],
    new_run_id: Callable[[str], str],
    log_event: Callable[..., None],
) -> dict[str, Any]:
    """Send a test Discord message implementation used by the API route wrapper."""
    require_valid_cron_token(x_cron_token)

    run_id = new_run_id("cron_discord_test")
    started_at = time.monotonic()
    log_event("cron.discord_test.started", run_id=run_id)

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

    await send_discord_webhook(payload)
    log_event(
        "cron.discord_test.completed",
        run_id=run_id,
        duration_ms=round((time.monotonic() - started_at) * 1000, 2),
    )
    return {"ok": True, "scheduled": True, "run_id": run_id}
