from typing import Any, Awaitable, Callable
import time


async def run_scheduler_job(
    *,
    job_name: str,
    runner: Callable[[str], Awaitable[dict[str, Any] | None]],
    new_run_id: Callable[[str], str],
    record_scheduler_heartbeat: Callable[..., None],
    log_event: Callable[..., None],
    on_success: Callable[[str, dict[str, Any], float], Awaitable[None]] | None = None,
) -> None:
    run_id = new_run_id(job_name)
    started_at = time.monotonic()
    record_scheduler_heartbeat(job_name, run_id, "started")
    log_event(f"scheduler.{job_name}.started", run_id=run_id)

    try:
        details = await runner(run_id)
        duration_ms = round((time.monotonic() - started_at) * 1000, 2)
        record_scheduler_heartbeat(
            job_name,
            run_id,
            "success",
            duration_ms=duration_ms,
        )
        log_event(
            f"scheduler.{job_name}.completed",
            run_id=run_id,
            duration_ms=duration_ms,
            **(details or {}),
        )
        if on_success is not None:
            await on_success(run_id, details or {}, duration_ms)
    except Exception as e:
        duration_ms = round((time.monotonic() - started_at) * 1000, 2)
        record_scheduler_heartbeat(
            job_name,
            run_id,
            "failure",
            duration_ms=duration_ms,
            error=str(e),
        )
        log_event(
            f"scheduler.{job_name}.failed",
            level="error",
            run_id=run_id,
            error_class=type(e).__name__,
            error=str(e),
            duration_ms=duration_ms,
        )
