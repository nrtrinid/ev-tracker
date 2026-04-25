import importlib
import os
import sys
import types
from collections.abc import Callable
from urllib.parse import urlparse

PRODUCTION_SUPABASE_PROJECT_REFS = {"xzeakifampttrqqhhibu"}


def supabase_project_ref(raw_url: str | None) -> str | None:
    if not raw_url:
        return None
    hostname = urlparse(raw_url.strip()).hostname or ""
    if not hostname.endswith(".supabase.co"):
        return None
    return hostname.split(".", 1)[0]


def require_non_production_supabase_for_tests() -> None:
    if os.getenv("ALLOW_PROD_TESTS") == "1":
        return

    url = os.getenv("TEST_SUPABASE_URL") or os.getenv("SUPABASE_URL")
    project_ref = supabase_project_ref(url)
    if project_ref in PRODUCTION_SUPABASE_PROJECT_REFS:
        raise RuntimeError(
            "Refusing to run tests against production Supabase. Set TEST_SUPABASE_URL/"
            "TEST_SUPABASE_SERVICE_ROLE_KEY for a dedicated test project, or set "
            "ALLOW_PROD_TESTS=1 for a deliberate one-off production check."
        )


def ensure_supabase_stub() -> None:
    if "supabase" in sys.modules:
        return
    supabase_mod = types.ModuleType("supabase")
    setattr(supabase_mod, "create_client", lambda *args, **kwargs: None)
    setattr(supabase_mod, "Client", object)
    sys.modules["supabase"] = supabase_mod


def import_or_reload(module_name: str):
    if module_name in sys.modules:
        return importlib.reload(sys.modules[module_name])
    return importlib.import_module(module_name)


def import_main_for_tests(monkeypatch, *, zoneinfo_zoneinfo_override: Callable | None = None):
    """Import/reload backend main with safe unit-test defaults and optional ZoneInfo override."""
    if zoneinfo_zoneinfo_override is not None:
        import zoneinfo as _zoneinfo_mod

        monkeypatch.setattr(_zoneinfo_mod, "ZoneInfo", zoneinfo_zoneinfo_override, raising=True)

    monkeypatch.setenv("SUPABASE_URL", os.getenv("SUPABASE_URL") or "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "unit-test-key")
    ensure_supabase_stub()
    return import_or_reload("main")


def reload_service_module(module_name: str):
    return import_or_reload(f"services.{module_name}")


def install_apscheduler_stubs(*, scheduler_cls):
    """Install minimal apscheduler module stubs for scheduler unit tests."""
    apscheduler_mod = types.ModuleType("apscheduler")
    schedulers_mod = types.ModuleType("apscheduler.schedulers")
    sched_asyncio_mod = types.ModuleType("apscheduler.schedulers.asyncio")
    triggers_mod = types.ModuleType("apscheduler.triggers")
    triggers_cron_mod = types.ModuleType("apscheduler.triggers.cron")
    triggers_interval_mod = types.ModuleType("apscheduler.triggers.interval")

    class CronTrigger:
        def __init__(self, *, hour, minute, timezone=None):
            self.hour = hour
            self.minute = minute
            self.timezone = timezone

    class IntervalTrigger:
        def __init__(self, *, minutes, start_date=None):
            self.minutes = minutes
            self.start_date = start_date

    setattr(sched_asyncio_mod, "AsyncIOScheduler", scheduler_cls)
    setattr(triggers_cron_mod, "CronTrigger", CronTrigger)
    setattr(triggers_interval_mod, "IntervalTrigger", IntervalTrigger)

    sys.modules.setdefault("apscheduler", apscheduler_mod)
    sys.modules.setdefault("apscheduler.schedulers", schedulers_mod)
    sys.modules.setdefault("apscheduler.schedulers.asyncio", sched_asyncio_mod)
    sys.modules.setdefault("apscheduler.triggers", triggers_mod)
    sys.modules.setdefault("apscheduler.triggers.cron", triggers_cron_mod)
    sys.modules.setdefault("apscheduler.triggers.interval", triggers_interval_mod)
