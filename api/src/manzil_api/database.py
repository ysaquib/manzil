"""Data-access seams (Phase 1 plan §1.1, §1.2; IMPLEMENTATION §2 DB-access rule).

Two independent strategies live side by side, matching the two processes:

- **asyncpg pool** — the API's direct Postgres access. When enabled, its
  in-process worker uses the same pool; the standalone worker creates an
  independent pool with the same service-level DSN and queue pattern.
- **supabase-py clients** — how the API performs user-context mutations: a
  request-scoped client authenticated with the *caller's* JWT, so PostgREST
  evaluates RLS with the real identity (what makes turning RLS on in Phase 2 a
  schema-only change). The anon and service clients are the two other flavors.

The API never hand-simulates permissions it can hand to the database.
"""

from __future__ import annotations

import asyncpg
from manzil_shared.config import POSTGRES_POOL_MAX_SIZE, POSTGRES_POOL_MIN_SIZE
from supabase._sync.client import SupabaseException

from manzil_api.config import Settings
from manzil_api.exceptions import BackendMisconfigured
from supabase import Client, create_client


def _create_client(url: str, key: str, *, key_name: str) -> Client:
    if not (key or "").strip():
        raise BackendMisconfigured(f"{key_name} is not configured")
    try:
        return create_client(url, key)
    except SupabaseException as exc:
        raise BackendMisconfigured(f"{key_name} is not configured") from exc


async def create_db_pool(settings: Settings) -> asyncpg.Pool:
    """Direct Postgres pool for API lifecycle work, sized for Supavisor."""
    return await asyncpg.create_pool(
        settings.database_url,
        min_size=POSTGRES_POOL_MIN_SIZE,
        max_size=POSTGRES_POOL_MAX_SIZE,
    )


def create_anon_client(settings: Settings) -> Client:
    """Anon-key client — RLS-safe, no user context. Used for unauthenticated reads."""
    return _create_client(
        settings.supabase_url, settings.supabase_anon_key, key_name="SUPABASE_ANON_KEY"
    )


def create_service_client(settings: Settings) -> Client:
    """Service-role client — bypasses RLS. Phase 1 holds it only for the
    in-process worker loop's needs; API request paths must prefer the
    user-token client so RLS (Phase 2) applies."""
    return _create_client(
        settings.supabase_url,
        settings.supabase_secret_key,
        key_name="SUPABASE_SECRET_KEY",
    )


def create_user_client(settings: Settings, access_token: str) -> Client:
    """Request-scoped client carrying the caller's JWT into PostgREST.

    Every service-layer mutation goes through one of these, so RLS sees the real
    user (Phase 1: RLS is off, but the identity already flows — Phase 2 flips a
    schema switch, not this code).
    """
    client = _create_client(
        settings.supabase_url, settings.supabase_anon_key, key_name="SUPABASE_ANON_KEY"
    )
    client.postgrest.auth(access_token)
    return client
