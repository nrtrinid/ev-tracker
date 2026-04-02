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
from utils.telemetry import rss_mb
from utils.time_utils import utc_now_iso_z


router = APIRouter()


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
    log_event(f"{log_prefix}.started", run_id=run_id, mode="daily_board")

    import main
    from services.daily_board import run_daily_board_drop

    started = utc_now_iso_z()
    errors: list[dict] = []
    result: dict | None = None
    try:
        async with main._DAILY_BOARD_RUN_LOCK:
            log_event(
                "board.drop.started_from_ops" if ops_status_key == "last_ops_trigger_scan" else "board.drop.started_from_cron",
                run_id=run_id,
                locked=main._DAILY_BOARD_RUN_LOCK.locked(),
                boot_id=getattr(main, "_BOOT_ID", None),
                pid=os.getpid(),
                rss_mb=rss_mb(),
            )
            result = await run_daily_board_drop(
                db=main.get_db(),
                source="ops_trigger_board_drop" if ops_status_key == "last_ops_trigger_scan" else "cron_board_drop",
                retry_supabase=main._retry_supabase,
                log_event=main._log_event,
            )
            if apply_fresh_scan_followups is not None and isinstance(result, dict):
                await apply_fresh_scan_followups(result)
    except Exception as exc:
        errors.append({"error": f"{type(exc).__name__}: {exc}"})

    finished = utc_now_iso_z()
    duration_ms = round((time.monotonic() - started_clock) * 1000, 2)
    log_event(
        f"{log_prefix}.completed",
        run_id=run_id,
        total_sides=(result or {}).get("props_sides") if isinstance(result, dict) else None,
        alerts_scheduled=0,
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
            "total_sides": (result or {}).get("props_sides") if isinstance(result, dict) else None,
            "alerts_scheduled": 0,
            "error_count": len(errors),
            "errors": errors,
            "captured_at": finished,
            "board_drop": True,
            "result": result,
        },
    )
    persist_ops_job_run(
        job_kind="ops_trigger_board_drop" if ops_status_key == "last_ops_trigger_scan" else "cron_board_drop",
        source="ops_trigger" if ops_status_key == "last_ops_trigger_scan" else "cron",
        status="completed" if not errors else "failed",
        run_id=run_id,
        scan_session_id=run_id,
        surface="board",
        scan_scope="daily_board",
        requested_sport="basketball_nba",
        captured_at=finished,
        started_at=started,
        finished_at=finished,
        duration_ms=duration_ms,
        events_fetched=None,
        events_with_both_books=None,
        total_sides=(result or {}).get("props_sides") if isinstance(result, dict) else None,
        alerts_scheduled=0,
        api_requests_remaining=None,
        hard_errors=len(errors) if errors else 0,
        error_count=len(errors),
        errors=errors,
        meta={"board_drop": True, "result": result},
    )

    return {
        "ok": not errors,
        "run_id": run_id,
        "started_at": started,
        "finished_at": finished,
        "duration_ms": duration_ms,
        "board_drop": True,
        "result": result,
        "errors": errors,
        "total_sides": (result or {}).get("props_sides") if isinstance(result, dict) else None,
        "alerts_scheduled": 0,
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
    started = utc_now_iso_z()
    weight_training_summary = None
    try:
        from services.odds_api import run_auto_settler
        from services.player_prop_weights import train_player_prop_model_weights

        settled = await run_auto_settler(db, source=auto_settle_source)
        try:
            weight_training_summary = train_player_prop_model_weights(db)
            log_event(
                f"{log_prefix}.weight_training.completed",
                run_id=run_id,
                **(weight_training_summary or {}),
            )
        except Exception as weight_exc:
            weight_training_summary = {
                "ok": False,
                "error_class": type(weight_exc).__name__,
                "error": str(weight_exc),
            }
            log_event(
                f"{log_prefix}.weight_training.failed",
                level="warning",
                run_id=run_id,
                error_class=type(weight_exc).__name__,
                error=str(weight_exc),
            )
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
        finished = utc_now_iso_z()

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
    auto_meta = None
    if isinstance(summary, dict):
        auto_meta = {}
        if isinstance(summary.get("sports"), list):
            auto_meta["sports"] = summary["sports"]
        if isinstance(summary.get("prop_settle_telemetry"), dict):
            auto_meta["prop_settle_telemetry"] = summary["prop_settle_telemetry"]
        if isinstance(weight_training_summary, dict):
            auto_meta["player_prop_weight_training"] = weight_training_summary
        if not auto_meta:
            auto_meta = None
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
        meta=auto_meta,
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


async def cron_run_jit_clv_impl(
    x_cron_token: str | None,
    *,
    require_valid_cron_token: Callable[[str | None], None],
    new_run_id: Callable[[str], str],
    log_event: Callable[..., None],
    set_ops_status: Callable[[str, dict], None],
    persist_ops_job_run: Callable[..., None],
    get_db: Callable[[], Any],
    run_id_prefix: str = "cron_jit_clv",
    log_prefix: str = "cron.jit_clv",
    ops_status_source: str = "cron",
) -> dict[str, Any]:
    """Capture closing reference odds for opportunities starting within close window."""
    require_valid_cron_token(x_cron_token)

    run_id = new_run_id(run_id_prefix)
    started_clock = time.monotonic()
    log_event(f"{log_prefix}.started", run_id=run_id)

    from services.odds_api import run_jit_clv_snatcher

    db = get_db()
    started = utc_now_iso_z()
    updated = 0
    try:
        updated = await run_jit_clv_snatcher(db)
        log_event(f"{log_prefix}.completed", run_id=run_id, updated=updated)
    except Exception as e:
        log_event(
            f"{log_prefix}.failed",
            level="error",
            run_id=run_id,
            error_class=type(e).__name__,
            error=str(e),
            duration_ms=round((time.monotonic() - started_clock) * 1000, 2),
        )
        raise HTTPException(status_code=502, detail=f"JIT CLV error: {e}")
    finally:
        finished = utc_now_iso_z()

    duration_ms = round((time.monotonic() - started_clock) * 1000, 2)

    set_ops_status(
        "last_jit_clv",
        {
            "source": ops_status_source,
            "run_id": run_id,
            "started_at": started,
            "finished_at": finished,
            "duration_ms": duration_ms,
            "updated": updated,
            "captured_at": finished,
        },
    )
    persist_ops_job_run(
        job_kind="jit_clv",
        source=ops_status_source,
        status="completed",
        run_id=run_id,
        captured_at=finished,
        started_at=started,
        finished_at=finished,
        duration_ms=duration_ms,
        meta={"updated": updated},
    )

    return {
        "ok": True,
        "run_id": run_id,
        "started_at": started,
        "finished_at": finished,
        "duration_ms": duration_ms,
        "updated": updated,
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
    model_version: str | None = None,
    capture_class: str | None = None,
    cohort_mode: str | None = None,
) -> ResearchOpportunitySummaryResponse:
    """Protected research summary implementation used by the API route wrapper."""
    require_valid_cron_token(x_cron_token)
    return get_summary(get_db(), model_version=model_version, capture_class=capture_class, cohort_mode=cohort_mode)


def ops_model_calibration_summary_impl(
    x_cron_token: str | None,
    *,
    require_valid_cron_token: Callable[[str | None], None],
    get_db: Callable[[], Any],
    get_summary: Callable[[Any], ModelCalibrationSummaryResponse],
) -> ModelCalibrationSummaryResponse:
    """Protected calibration summary implementation used by the API route wrapper."""
    require_valid_cron_token(x_cron_token)
    return get_summary(get_db())


def ops_pickem_research_summary_impl(
    x_cron_token: str | None,
    *,
    require_valid_cron_token: Callable[[str | None], None],
    get_db: Callable[[], Any],
    get_summary: Callable[[Any], PickEmResearchSummaryResponse],
) -> PickEmResearchSummaryResponse:
    """Protected pick'em research summary implementation used by the API route wrapper."""
    require_valid_cron_token(x_cron_token)
    return get_summary(get_db())


def ops_clv_debug_impl(
    x_cron_token: str | None,
    *,
    require_valid_cron_token: Callable[[str | None], None],
    get_db: Callable[[], Any],
    retry_supabase: Callable[[Callable[[], Any]], Any],
    load_snapshot: Callable[..., dict[str, Any]],
    load_scheduler_job_snapshot: Callable[..., dict[str, Any]],
    utc_now_iso: Callable[[], str],
) -> dict[str, Any]:
    require_valid_cron_token(x_cron_token)
    return load_snapshot(
        get_db(),
        retry_supabase=retry_supabase,
        load_scheduler_job_snapshot=load_scheduler_job_snapshot,
        utc_now_iso=utc_now_iso,
    )


async def ops_replay_recent_clv_impl(
    x_cron_token: str | None,
    *,
    require_valid_cron_token: Callable[[str | None], None],
    get_db: Callable[[], Any],
    replay_recent_closes: Callable[..., Any],
    lookback_hours: int,
) -> dict[str, Any]:
    require_valid_cron_token(x_cron_token)
    return await replay_recent_closes(get_db(), lookback_hours=lookback_hours)


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
                    {"name": "Server time (UTC)", "value": utc_now_iso_z(), "inline": False},
                ],
            }
        ]
    }

    try:
        await send_discord_webhook(payload, message_type="test")
    except TypeError as exc:
        if "message_type" not in str(exc):
            raise
        await send_discord_webhook(payload)
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
    return {"ok": True, "scheduled": True, "run_id": run_id}


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
                    {"name": "Server time (UTC)", "value": utc_now_iso_z(), "inline": False},
                ],
            }
        ]
    }

    try:
        await send_discord_webhook(payload, message_type="alert")
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
    return {"ok": True, "scheduled": True, "run_id": run_id}


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
        apply_fresh_scan_followups=lambda result: main._apply_fresh_board_drop_followups(
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


@router.post("/api/ops/trigger/jit-clv")
async def ops_trigger_jit_clv(
    x_ops_token: str | None = Header(default=None, alias="X-Ops-Token"),
    x_cron_token: str | None = Header(default=None, alias="X-Cron-Token"),
    _auth: None = Depends(require_ops_token),
):
    import main

    return await cron_run_jit_clv_impl(
        x_cron_token=x_ops_token or x_cron_token,
        require_valid_cron_token=lambda token: main._require_ops_token(token, None),
        new_run_id=main._new_run_id,
        log_event=main._log_event,
        set_ops_status=main._set_ops_status,
        persist_ops_job_run=main._persist_ops_job_run,
        get_db=main.get_db,
        run_id_prefix="ops_jit_clv",
        log_prefix="ops.trigger.jit_clv",
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
    x_ops_token: str | None = Header(default=None, alias="X-Ops-Token"),
    x_cron_token: str | None = Header(default=None, alias="X-Cron-Token"),
    model_version: str | None = Query(default=None),
    capture_class: str | None = Query(default=None),
    cohort_mode: str | None = Query(default=None),
    _auth: None = Depends(require_ops_token),
):
    import main
    from services.research_opportunities import get_research_opportunities_summary

    return ops_research_opportunities_summary_impl(
        x_cron_token=x_ops_token or x_cron_token,
        require_valid_cron_token=lambda token: main._require_ops_token(token, None),
        get_db=main.get_db,
        get_summary=get_research_opportunities_summary,
        model_version=model_version,
        capture_class=capture_class,
        cohort_mode=cohort_mode,
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
    from services.ops_history import load_scheduler_job_snapshot

    return ops_clv_debug_impl(
        x_cron_token=x_ops_token or x_cron_token,
        require_valid_cron_token=lambda token: main._require_ops_token(token, None),
        get_db=main.get_db,
        retry_supabase=main._retry_supabase,
        load_snapshot=build_clv_audit_snapshot,
        load_scheduler_job_snapshot=load_scheduler_job_snapshot,
        utc_now_iso=main._utc_now_iso,
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
        get_db=main.get_db,
        replay_recent_closes=replay_recent_clv_closes,
        lookback_hours=lookback_hours,
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
