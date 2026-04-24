"""
EV Tracker API app composition.

Business logic lives in route and service modules; this file owns only FastAPI
construction, middleware, lifespan, and router registration.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services import ops_runtime
from services.app_bootstrap import validate_environment
from services.scheduler_runtime import start_scheduler, stop_scheduler

load_dotenv()

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO), format="%(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    ops_runtime.configure_app(app)
    validate_environment()
    ops_runtime.init_ops_status()
    await start_scheduler(app)
    try:
        yield
    finally:
        await stop_scheduler(app)


app = FastAPI(
    title="EV Tracker API",
    description="Track sports betting Expected Value",
    version="1.0.0",
    lifespan=lifespan,
)
ops_runtime.configure_app(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

from routes.admin_routes import router as admin_router
from routes.analytics_routes import router as analytics_router
from routes.beta_access_routes import router as beta_access_router
from routes.bet_routes import router as bet_router
from routes.board_routes import router as board_router
from routes.dashboard_routes import router as dashboard_router
from routes.health_routes import router as health_router
from routes.ops_cron import router as ops_router
from routes.parlay_routes import router as parlay_router
from routes.scan_routes import router as scan_router
from routes.settings_routes import router as settings_router
from routes.transactions_routes import router as transactions_router
from routes.utility_routes import router as utility_router

app.include_router(health_router)
app.include_router(bet_router)
app.include_router(dashboard_router)
app.include_router(scan_router)
app.include_router(board_router, prefix="/api")
app.include_router(ops_router)
app.include_router(settings_router)
app.include_router(transactions_router)
app.include_router(parlay_router)
app.include_router(utility_router)
app.include_router(admin_router)
app.include_router(analytics_router)
app.include_router(beta_access_router)
