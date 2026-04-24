"""Application startup validation and scheduler-worker orchestration."""

from __future__ import annotations

import asyncio
import os

from fastapi import FastAPI

from services import ops_runtime
from services.paper_autolog_runner import (
    is_paper_experiment_autolog_enabled,
    paper_experiment_account_user_id,
)
from services.runtime_support import app_role, log_event
from services.scheduler_runtime import (
    DISCORD_SCAN_ALERT_MODE_ENV,
    SCHEDULED_SCAN_TEMP_TIME_ENV,
    parse_hhmm,
    scan_alert_mode,
    scan_alert_mode_raw,
    start_scheduler,
    stop_scheduler,
)


def validate_environment() -> None:
    required = ["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    environment = os.getenv("ENVIRONMENT", "production").lower()
    if environment not in {"development", "production", "testing", "staging"}:
        log_event(
            "startup.env_environment_unexpected",
            level="warning",
            environment=environment,
        )

    role = app_role()
    scheduler_enabled = os.getenv("ENABLE_SCHEDULER") == "1"
    odds_api_configured = bool(os.getenv("ODDS_API_KEY"))
    cron_token_configured = bool(os.getenv("CRON_TOKEN"))
    paper_autolog_enabled = is_paper_experiment_autolog_enabled()
    paper_autolog_user_id = paper_experiment_account_user_id()
    temp_scan_time_raw = os.getenv(SCHEDULED_SCAN_TEMP_TIME_ENV)
    heartbeat_enabled = os.getenv("DISCORD_AUTO_SETTLE_HEARTBEAT") == "1"
    raw_alert_mode = scan_alert_mode_raw()
    resolved_alert_mode = scan_alert_mode()
    discord_alert_target = {
        "webhook_configured": False,
        "route_kind": "alert_unconfigured",
    }
    discord_test_target = {
        "webhook_configured": False,
        "route_kind": "test_unconfigured",
    }

    try:
        from services.discord_alerts import describe_discord_delivery_target

        discord_alert_target = describe_discord_delivery_target(
            "alert",
            delivery_context="scheduled_board_drop",
        )
        discord_test_target = describe_discord_delivery_target("test")
    except Exception:
        pass

    alert_route_kind = str(discord_alert_target.get("route_kind") or "")
    alert_route_disabled = alert_route_kind == "alert_disabled"

    if scheduler_enabled and not odds_api_configured:
        log_event(
            "startup.env_scheduler_without_odds_key",
            level="warning",
            message="ENABLE_SCHEDULER=1 but ODDS_API_KEY is missing; scan jobs will fail.",
        )

    if role == "api" and scheduler_enabled:
        log_event(
            "startup.env_split_role_mismatch",
            level="warning",
            app_role=role,
            scheduler_enabled=scheduler_enabled,
            message="APP_ROLE=api should use ENABLE_SCHEDULER=0 in split-role deployments.",
        )

    if role == "scheduler" and not scheduler_enabled:
        log_event(
            "startup.env_split_role_mismatch",
            level="warning",
            app_role=role,
            scheduler_enabled=scheduler_enabled,
            message="APP_ROLE=scheduler should use ENABLE_SCHEDULER=1 in split-role deployments.",
        )

    if not cron_token_configured:
        log_event(
            "startup.env_cron_token_missing",
            level="warning",
            message="CRON_TOKEN is missing; cron endpoints will reject requests.",
        )

    if scheduler_enabled and alert_route_disabled:
        log_event(
            "startup.env_discord_alert_route_disabled",
            route_kind=alert_route_kind,
            message=(
                "DISCORD_ENABLE_ALERT_ROUTE=0; alert-path Discord delivery is disabled. "
                "Only debug/test routing is active."
            ),
        )

    if (
        scheduler_enabled
        and not alert_route_disabled
        and not bool(discord_alert_target.get("webhook_configured"))
    ):
        log_event(
            "startup.env_discord_alert_webhook_missing",
            level="warning",
            route_kind=discord_alert_target.get("route_kind"),
            message="ENABLE_SCHEDULER=1 but no alert Discord webhook is configured; alert delivery is disabled.",
        )

    if heartbeat_enabled and not bool(discord_test_target.get("webhook_configured")):
        log_event(
            "startup.env_discord_debug_webhook_missing",
            level="warning",
            route_kind=discord_test_target.get("route_kind"),
            message="DISCORD_AUTO_SETTLE_HEARTBEAT=1 but no debug/test Discord webhook is configured.",
        )

    if paper_autolog_enabled and not paper_autolog_user_id:
        log_event(
            "startup.env_paper_autolog_without_user_id",
            level="warning",
            message="Paper autolog is enabled but no account user id is configured; autolog inserts will be skipped.",
        )

    if temp_scan_time_raw and parse_hhmm(temp_scan_time_raw) is None:
        log_event(
            "startup.env_temp_scan_time_invalid",
            level="warning",
            env_var=SCHEDULED_SCAN_TEMP_TIME_ENV,
            provided_value=temp_scan_time_raw,
            message="Invalid temp scan time format; expected HH:MM in 24h format.",
        )

    if raw_alert_mode != resolved_alert_mode:
        log_event(
            "startup.env_scan_alert_mode_invalid",
            level="warning",
            env_var=DISCORD_SCAN_ALERT_MODE_ENV,
            provided_value=raw_alert_mode,
            defaulted_to=resolved_alert_mode,
            message="Unsupported scan alert mode; defaulting to timed_ping.",
        )

    log_event(
        "startup.env_validated",
        environment=environment,
        scheduler_enabled=scheduler_enabled,
        cron_token_configured=cron_token_configured,
        odds_api_key_configured=odds_api_configured,
        discord_alert_route_enabled=not alert_route_disabled,
        discord_alert_webhook_configured=bool(discord_alert_target.get("webhook_configured")),
        discord_alert_route_kind=discord_alert_target.get("route_kind"),
        discord_test_webhook_configured=bool(discord_test_target.get("webhook_configured")),
        discord_test_route_kind=discord_test_target.get("route_kind"),
        discord_heartbeat_enabled=heartbeat_enabled,
        discord_scan_alert_mode=resolved_alert_mode,
        paper_autolog_enabled=paper_autolog_enabled,
        paper_autolog_user_id_configured=bool(paper_autolog_user_id),
    )


async def run_scheduler_worker(app: FastAPI) -> None:
    ops_runtime.configure_app(app)
    validate_environment()
    ops_runtime.init_ops_status()
    await start_scheduler(app)

    try:
        while True:
            await asyncio.sleep(3600)
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        await stop_scheduler(app)
