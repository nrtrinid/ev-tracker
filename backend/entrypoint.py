from __future__ import annotations

import asyncio
import os

import uvicorn

from main import app
from services.app_bootstrap import run_scheduler_worker
from services.runtime_support import app_role


def _uvicorn_workers() -> int:
    try:
        return max(1, int(os.getenv("UVICORN_WORKERS", "1")))
    except Exception:
        return 1


def main_entry() -> None:
    role = app_role()
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    log_level = os.getenv("UVICORN_LOG_LEVEL", "info")

    if role == "scheduler":
        asyncio.run(run_scheduler_worker(app))
        return

    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        workers=_uvicorn_workers(),
        log_level=log_level,
    )


if __name__ == "__main__":
    main_entry()
