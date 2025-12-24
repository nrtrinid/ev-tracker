"""
Database Connection
Handles Supabase client initialization.
"""

import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_ANON_KEY environment variables")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def get_db() -> Client:
    """Get Supabase client instance."""
    return supabase
