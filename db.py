"""Supabase client factory — the sole DB abstraction for the Flask app.

No more SQLite. Everything (users/profiles, projects, project_assets,
script_versions) reads and writes through Supabase's public schema, which
is where PI's real data already lives.

Reads env:
    SUPABASE_URL         — https://<project>.supabase.co
    SUPABASE_SERVICE_KEY — service_role key (admin scope, server-side only)
"""
from __future__ import annotations

import os
from functools import lru_cache

from supabase import create_client, Client


@lru_cache(maxsize=1)
def get_sb() -> Client:
    """Return a cached Supabase client using the service key (server-side scope).

    Cached across requests because create_client sets up an HTTP session and
    we don't want to rebuild it on every DB touch. supabase-py's HTTP client
    is thread-safe under Flask's request handling model.
    """
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
    return create_client(url, key)


# Backwards-compat shims for the code that still calls db.get_conn() or db.init_db().
# get_conn() returns the Supabase client (call sites that used conn.execute()
# have all been migrated to sb.table(...).method() calls; anything remaining
# raises loudly so it can be caught in review).
def get_conn():
    raise RuntimeError("get_conn() is dead — use db.get_sb() and .table() queries")


def init_db() -> None:
    """No-op — Supabase schema is managed in the Supabase dashboard, not here."""
    pass
