from typing import Any, Awaitable, Callable, Iterable, cast

import httpx

from models import FullScanResponse


async def run_scheduled_scan_sports(
    *,
    run_id: str,
    supported_sports: Iterable[str],
    get_cached_or_scan: Callable[[str], Awaitable[dict[str, Any]]],
    schedule_alerts: Callable[[list[dict[str, Any]]], int],
    log_event: Callable[..., None],
) -> dict[str, Any]:
    total_sides = 0
    alerts_scheduled = 0
    hard_errors = 0
    all_sides: list[dict[str, Any]] = []
    total_events = 0
    total_with_both = 0
    min_remaining: str | None = None
    oldest_fetched: float | None = None

    for sport_key in supported_sports:
        try:
            result = await get_cached_or_scan(sport_key)
            sides_count = len(result.get("sides") or [])
            fetched = result.get("events_fetched")
            with_both = result.get("events_with_both_books")
            sides = result.get("sides") or []
            all_sides.extend(sides)
            total_sides += len(sides)
            total_events += int(fetched or 0)
            total_with_both += int(with_both or 0)

            rem = result.get("api_requests_remaining")
            if rem is not None:
                try:
                    r = int(rem)
                    min_remaining = str(r) if min_remaining is None else str(min(r, int(min_remaining)))
                except ValueError:
                    min_remaining = str(rem)

            ft = result.get("fetched_at")
            if ft is not None:
                oldest_fetched = ft if oldest_fetched is None else min(oldest_fetched, ft)

            alerts_scheduled += schedule_alerts(sides)
            log_event(
                "scheduler.scan.sport_completed",
                run_id=run_id,
                sport=sport_key,
                sides=sides_count,
                events_fetched=fetched,
                events_with_both_books=with_both,
            )
        except httpx.HTTPStatusError as e:
            if e.response is not None and e.response.status_code == 404:
                log_event(
                    "scheduler.scan.sport_skipped",
                    run_id=run_id,
                    sport=sport_key,
                    status=404,
                    reason="no odds",
                )
                continue
            log_event(
                "scheduler.scan.sport_failed",
                level="error",
                run_id=run_id,
                sport=sport_key,
                error_class=type(e).__name__,
                error=str(e),
            )
            hard_errors += 1
        except Exception as e:
            log_event(
                "scheduler.scan.sport_failed",
                level="error",
                run_id=run_id,
                sport=sport_key,
                error_class=type(e).__name__,
                error=str(e),
            )
            hard_errors += 1

    return {
        "total_sides": total_sides,
        "alerts_scheduled": alerts_scheduled,
        "hard_errors": hard_errors,
        "all_sides": all_sides,
        "total_events": total_events,
        "total_with_both": total_with_both,
        "min_remaining": min_remaining,
        "oldest_fetched": oldest_fetched,
    }


def persist_latest_scheduled_scan_payload(
    *,
    all_sides: list[dict[str, Any]],
    total_events: int,
    total_with_both: int,
    min_remaining: str | None,
    scanned_at: str,
    persist_latest_payload: Callable[[dict[str, Any]], None],
) -> None:
    payload = FullScanResponse(
        sport="all",
        sides=cast(Any, all_sides),
        events_fetched=total_events,
        events_with_both_books=total_with_both,
        api_requests_remaining=min_remaining,
        scanned_at=scanned_at,
    ).model_dump()
    persist_latest_payload(payload)


def maybe_send_scheduled_scan_no_alert_heartbeat(
    *,
    heartbeat_enabled: bool,
    started: str,
    finished: str,
    total_sides: int,
    alerts_scheduled: int,
    send_discord_webhook: Callable[[dict[str, Any]], Awaitable[Any]],
    create_task: Callable[[Any], Any],
) -> None:
    if not heartbeat_enabled or alerts_scheduled != 0:
        return

    payload = {
        "embeds": [
            {
                "title": "Scheduled scan complete (no alerts)",
                "description": "The scheduled scan ran successfully but found no qualifying lines to alert on.",
                "fields": [
                    {"name": "Started (UTC)", "value": started + "Z", "inline": True},
                    {"name": "Finished (UTC)", "value": finished + "Z", "inline": True},
                    {"name": "Total sides", "value": str(total_sides), "inline": True},
                    {"name": "Alerts scheduled", "value": str(alerts_scheduled), "inline": True},
                ],
            }
        ]
    }
    create_task(send_discord_webhook(payload, message_type="heartbeat"))


async def run_scheduled_scan_autolog(
    *,
    run_id: str,
    all_sides: list[dict[str, Any]],
    run_autolog: Callable[..., Awaitable[dict[str, Any] | None]],
    is_autolog_enabled: Callable[[], bool],
    log_event: Callable[..., None],
) -> dict[str, Any] | None:
    try:
        return await run_autolog(run_id=run_id, sides=all_sides)
    except Exception as e:
        log_event(
            "scheduler.scan.autolog.failed",
            level="error",
            run_id=run_id,
            error_class=type(e).__name__,
            error=str(e),
        )
        return {
            "enabled": is_autolog_enabled(),
            "error": f"{type(e).__name__}: {e}",
        }


def finalize_scheduled_scan_run(
    *,
    run_id: str,
    started: str,
    finished: str,
    duration_ms: float,
    total_sides: int,
    alerts_scheduled: int,
    hard_errors: int,
    autolog_summary: dict[str, Any] | None,
    log_event: Callable[..., None],
    record_scheduler_heartbeat: Callable[..., None],
    set_ops_status: Callable[[str, dict[str, Any]], None],
) -> None:
    log_event(
        "scheduler.scan.completed",
        run_id=run_id,
        finished_at=finished + "Z",
        total_sides=total_sides,
        alerts_scheduled=alerts_scheduled,
        autolog_summary=autolog_summary,
        duration_ms=duration_ms,
    )
    if hard_errors:
        record_scheduler_heartbeat(
            "scheduled_scan",
            run_id,
            "failure",
            duration_ms=duration_ms,
            error=f"{hard_errors} sport(s) failed",
        )
    else:
        record_scheduler_heartbeat(
            "scheduled_scan",
            run_id,
            "success",
            duration_ms=duration_ms,
        )

    set_ops_status(
        "last_scheduler_scan",
        {
            "run_id": run_id,
            "started_at": started + "Z",
            "finished_at": finished + "Z",
            "duration_ms": duration_ms,
            "total_sides": total_sides,
            "alerts_scheduled": alerts_scheduled,
            "hard_errors": hard_errors,
            "autolog_summary": autolog_summary,
        },
    )
