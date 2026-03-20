import pytest
import httpx

from services.scheduler_bootstrap import (
    build_auto_settle_trigger,
    register_scheduled_scan_jobs,
    mark_scheduler_started,
    shutdown_scheduler,
)
from services.scheduler_runner import run_scheduler_job
from services.scheduler_scan import (
    run_scheduled_scan_sports,
    persist_latest_scheduled_scan_payload,
)


class _DummyCronTrigger:
    def __init__(self, hour, minute, timezone=None):
        self.hour = hour
        self.minute = minute
        self.timezone = timezone


class _DummyScheduler:
    def __init__(self):
        self.jobs = []
        self.shutdown_called = False
        self.shutdown_wait = None

    def add_job(self, func, trigger, **kwargs):
        self.jobs.append({"func": func, "trigger": trigger, "kwargs": kwargs})

    def shutdown(self, wait=False):
        self.shutdown_called = True
        self.shutdown_wait = wait


class _DummyState:
    scheduler_started_at = None
    scheduler = None


def test_build_auto_settle_trigger_uses_timezone_when_available():
    tz = object()
    trigger = build_auto_settle_trigger(cron_trigger_cls=_DummyCronTrigger, phoenix_tz=tz)
    assert trigger.hour == 4
    assert trigger.minute == 0
    assert trigger.timezone is tz


def test_register_scheduled_scan_jobs_registers_default_and_temp_times():
    scheduler = _DummyScheduler()

    register_scheduled_scan_jobs(
        scheduler=scheduler,
        cron_trigger_cls=_DummyCronTrigger,
        phoenix_tz=object(),
        temp_scan_time_raw="14:45",
        parse_hhmm=lambda raw: (14, 45) if raw == "14:45" else None,
        merge_scan_times=lambda base, temp: base + ([temp] if temp else []),
        run_scheduled_scan_job=lambda: None,
        print_fn=lambda _msg: None,
    )

    assert len(scheduler.jobs) == 3
    times = {(j["trigger"].hour, j["trigger"].minute) for j in scheduler.jobs}
    assert times == {(16, 30), (18, 30), (14, 45)}


def test_mark_and_shutdown_scheduler_lifecycle():
    scheduler = _DummyScheduler()
    state = _DummyState()
    events = []

    mark_scheduler_started(
        scheduler=scheduler,
        app_state=state,
        utc_now_iso=lambda: "2026-03-19T00:00:00Z",
        log_event=lambda event, **fields: events.append((event, fields)),
    )
    shutdown_scheduler(scheduler=scheduler, log_event=lambda event, **fields: events.append((event, fields)))

    assert state.scheduler is scheduler
    assert state.scheduler_started_at == "2026-03-19T00:00:00Z"
    assert scheduler.shutdown_called is True
    assert scheduler.shutdown_wait is False
    assert any(e[0] == "scheduler.started" for e in events)
    assert any(e[0] == "scheduler.stopped" for e in events)


@pytest.mark.asyncio
async def test_run_scheduler_job_success_and_failure_paths():
    heartbeats = []
    events = []
    success_calls = []

    async def _ok_runner(_run_id):
        return {"updated": 2}

    async def _on_success(run_id, details, duration_ms):
        success_calls.append((run_id, details, duration_ms))

    await run_scheduler_job(
        job_name="jit_clv",
        runner=_ok_runner,
        new_run_id=lambda name: f"{name}-run",
        record_scheduler_heartbeat=lambda *args, **kwargs: heartbeats.append((args, kwargs)),
        log_event=lambda event, **fields: events.append((event, fields)),
        on_success=_on_success,
    )

    async def _bad_runner(_run_id):
        raise RuntimeError("boom")

    await run_scheduler_job(
        job_name="jit_clv",
        runner=_bad_runner,
        new_run_id=lambda name: f"{name}-run-2",
        record_scheduler_heartbeat=lambda *args, **kwargs: heartbeats.append((args, kwargs)),
        log_event=lambda event, **fields: events.append((event, fields)),
    )

    assert any(e[0] == "scheduler.jit_clv.completed" for e in events)
    assert any(e[0] == "scheduler.jit_clv.failed" for e in events)
    assert len(success_calls) == 1


@pytest.mark.asyncio
async def test_run_scheduled_scan_sports_continues_after_404_and_error():
    logs = []

    async def _get_cached_or_scan(sport):
        if sport == "missing":
            req = httpx.Request("GET", "https://example.test")
            resp = httpx.Response(404, request=req)
            raise httpx.HTTPStatusError("not found", request=req, response=resp)
        if sport == "broken":
            raise RuntimeError("boom")
        return {
            "sides": [{"id": sport}],
            "events_fetched": 1,
            "events_with_both_books": 1,
            "api_requests_remaining": "99",
            "fetched_at": 1700000000.0,
        }

    summary = await run_scheduled_scan_sports(
        run_id="r1",
        supported_sports=["ok", "missing", "broken"],
        get_cached_or_scan=_get_cached_or_scan,
        schedule_alerts=lambda sides: len(sides),
        log_event=lambda event, **fields: logs.append((event, fields)),
    )

    assert summary["total_sides"] == 1
    assert summary["alerts_scheduled"] == 1
    assert summary["hard_errors"] == 1
    assert any(event == "scheduler.scan.sport_skipped" for event, _ in logs)
    assert any(event == "scheduler.scan.sport_failed" for event, _ in logs)


def test_persist_latest_scheduled_scan_payload_calls_callback_with_payload():
    captured = {}

    persist_latest_scheduled_scan_payload(
        all_sides=[],
        total_events=0,
        total_with_both=0,
        min_remaining="100",
        scanned_at="2026-03-19T00:00:00Z",
        persist_latest_payload=lambda payload: captured.update(payload),
    )

    assert captured["sport"] == "all"
    assert captured["events_fetched"] == 0
