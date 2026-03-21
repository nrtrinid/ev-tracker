"""
Database Connection
Handles Supabase client initialization.
"""

import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

_supabase: Client | None = None

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
        _supabase = create_client(url, key)
    return _supabase
