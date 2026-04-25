"""
Database Connection
Handles Supabase client initialization.
"""

import os
from supabase import create_client, Client
from dotenv import load_dotenv
from urllib.parse import urlparse

load_dotenv()

_supabase: Client | None = None
PRODUCTION_SUPABASE_PROJECT_REFS = {"xzeakifampttrqqhhibu"}


def _supabase_project_ref(raw_url: str | None) -> str | None:
    if not raw_url:
        return None
    hostname = urlparse(raw_url.strip()).hostname or ""
    if not hostname.endswith(".supabase.co"):
        return None
    return hostname.split(".", 1)[0]


def _guard_test_database(url: str | None) -> None:
    if os.getenv("TESTING") != "1" or os.getenv("ALLOW_PROD_TESTS") == "1":
        return
    if _supabase_project_ref(url) in PRODUCTION_SUPABASE_PROJECT_REFS:
        raise RuntimeError(
            "Refusing to initialize production Supabase while TESTING=1. "
            "Use TEST_SUPABASE_URL/TEST_SUPABASE_SERVICE_ROLE_KEY for live integration "
            "tests, or set ALLOW_PROD_TESTS=1 for a deliberate one-off production check."
        )

def get_db() -> Client:
    """Get Supabase client instance (service role, bypasses RLS). Lazily initializes the client."""
    global _supabase
    if _supabase is None:
        # When TESTING=1, optional test project env vars allow a separate Supabase for integration tests
        if os.getenv("TESTING") == "1":
            url = os.getenv("TEST_SUPABASE_URL") or os.getenv("SUPABASE_URL")
            key = os.getenv("TEST_SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        else:
            url = os.getenv("SUPABASE_URL")
            key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        if not url or not key:
            raise ValueError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY environment variables")
        _guard_test_database(url)
        _supabase = create_client(url, key)
    return _supabase
