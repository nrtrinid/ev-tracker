from __future__ import annotations

import asyncio
import os

import uvicorn

import main


def _uvicorn_workers() -> int:
    try:
        return max(1, int(os.getenv("UVICORN_WORKERS", "1")))
    except Exception:
        return 1


def main_entry() -> None:
    role = main._app_role()
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    log_level = os.getenv("UVICORN_LOG_LEVEL", "info")

    if role == "scheduler":
        asyncio.run(main.run_scheduler_worker())
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
