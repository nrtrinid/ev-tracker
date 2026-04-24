from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException

from services.ops_runtime import (
    check_db_ready,
    check_scheduler_freshness,
    persist_ops_job_run,
    runtime_state,
    set_ops_status,
)
from services.runtime_support import log_event, utc_now_iso

router = APIRouter()


@router.get("/health")
def health_check():
    return {"status": "healthy", "timestamp": datetime.now(UTC).isoformat()}


@router.get("/ready")
def readiness_check():
    runtime = runtime_state()
    db_ok, db_error = check_db_ready()
    scheduler_fresh_ok, scheduler_freshness = check_scheduler_freshness(runtime["scheduler_expected"])
    import os

    app_role = (os.getenv("APP_ROLE") or "").strip().lower()
    scheduler_state_ok = (not runtime["scheduler_expected"]) or runtime["scheduler_running"]
    if not scheduler_state_ok and app_role == "api":
        scheduler_state_ok = True

    scheduler_fresh_check_ok = scheduler_fresh_ok if app_role != "api" else True
    checks = {
        "supabase_env": runtime["supabase_url_configured"] and runtime["supabase_service_role_configured"],
        "db_connectivity": db_ok,
        "scheduler_state": scheduler_state_ok,
        "scheduler_freshness": scheduler_fresh_check_ok,
    }
    ready = all(checks.values())

    if not ready:
        log_event(
            "readiness.failed",
            level="warning",
            checks=checks,
            db_error=db_error,
            runtime=runtime,
        )
        set_ops_status(
            "last_readiness_failure",
            {
                "captured_at": utc_now_iso(),
                "checks": checks,
                "db_error": db_error,
            },
        )
        persist_ops_job_run(
            job_kind="readiness_failure",
            source="readiness",
            status="failed",
            captured_at=utc_now_iso(),
            checks=checks,
            meta={"db_error": db_error, "runtime": runtime},
        )

    response = {
        "status": "ready" if ready else "not_ready",
        "timestamp": utc_now_iso(),
        "checks": checks,
        "runtime": runtime,
        "scheduler_freshness": scheduler_freshness,
    }
    if db_error:
        response["db_error"] = db_error

    if ready:
        return response

    raise HTTPException(status_code=503, detail=response)
