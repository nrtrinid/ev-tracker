"""
Database Connection
Handles Supabase client initialization.
"""

import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

# When TESTING=1, optional test project env vars allow a separate Supabase for integration tests
if os.getenv("TESTING") == "1":
    SUPABASE_URL = os.getenv("TEST_SUPABASE_URL") or os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("TEST_SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
else:
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY environment variables")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def get_db() -> Client:
    """Get Supabase client instance (service role, bypasses RLS)."""
    return supabase
