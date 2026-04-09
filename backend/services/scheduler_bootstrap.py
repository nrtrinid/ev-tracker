from typing import Any, Callable


def build_auto_settle_trigger(*, cron_trigger_cls, phoenix_tz):
    return (
        cron_trigger_cls(hour=4, minute=0, timezone=phoenix_tz)
        if phoenix_tz is not None
        else cron_trigger_cls(hour=4, minute=0)
    )


def register_scheduled_scan_jobs(
    *,
    scheduler,
    cron_trigger_cls,
    phoenix_tz,
    temp_scan_time_raw: str | None,
    parse_hhmm: Callable[[str | None], tuple[int, int] | None],
    merge_scan_times: Callable[[list[tuple[int, int]], tuple[int, int] | None], list[tuple[int, int]]],
    run_scheduled_scan_job,
    print_fn: Callable[[str], Any] = print,
) -> None:
    if phoenix_tz is None:
        print_fn("[Scheduler] Phoenix timezone unavailable; skipping scheduled scan jobs.")
        return

    temp_scan_time = parse_hhmm(temp_scan_time_raw)
    scan_times = merge_scan_times([(10, 30), (15, 30)], temp_scan_time)
    for hour, minute in scan_times:
        scheduler.add_job(
            run_scheduled_scan_job,
            cron_trigger_cls(hour=hour, minute=minute, timezone=phoenix_tz),
        )


def mark_scheduler_started(*, scheduler, app_state, utc_now_iso: Callable[[], str], log_event: Callable[..., None]) -> None:
    app_state.scheduler_started_at = utc_now_iso()
    if hasattr(scheduler, "get_jobs"):
        jobs_count = len(scheduler.get_jobs())
    else:
        jobs_count = len(getattr(scheduler, "jobs", []))
    log_event("scheduler.started", jobs=jobs_count)
    app_state.scheduler = scheduler


def shutdown_scheduler(*, scheduler, log_event: Callable[..., None]) -> None:
    scheduler.shutdown(wait=False)
    log_event("scheduler.stopped")
