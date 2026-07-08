"""Data-access seams (Phase 1 plan §1.1, §1.2; IMPLEMENTATION §2 DB-access rule).

Two independent strategies live side by side, matching the two processes:

- **asyncpg pool** — the in-process worker loop's direct, service-role Postgres
  access (the worker's own pattern, `FOR UPDATE SKIP LOCKED` etc.). Held on
  `app.state.db_pool`, created/closed by the lifespan.
- **supabase-py clients** — how the API performs user-context mutations: a
  request-scoped client authenticated with the *caller's* JWT, so PostgREST
  evaluates RLS with the real identity (what makes turning RLS on in Phase 2 a
  schema-only change). The anon and service clients are the two other flavors.

The API never hand-simulates permissions it can hand to the database.
"""

from __future__ import annotations

import asyncpg

from manzil_api.config import Settings
from supabase import Client, create_client


async def create_db_pool(settings: Settings) -> asyncpg.Pool:
    """Direct Postgres pool for the in-process worker loop (service-level)."""
    return await asyncpg.create_pool(settings.database_url)


def create_anon_client(settings: Settings) -> Client:
    """Anon-key client — RLS-safe, no user context. Used for unauthenticated reads."""
    return create_client(settings.supabase_url, settings.supabase_anon_key)


def create_service_client(settings: Settings) -> Client:
    """Service-role client — bypasses RLS. Phase 1 holds it only for the
    in-process worker loop's needs; API request paths must prefer the
    user-token client so RLS (Phase 2) applies."""
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def create_user_client(settings: Settings, access_token: str) -> Client:
    """Request-scoped client carrying the caller's JWT into PostgREST.

    Every service-layer mutation goes through one of these, so RLS sees the real
    user (Phase 1: RLS is off, but the identity already flows — Phase 2 flips a
    schema switch, not this code).
    """
    client = create_client(settings.supabase_url, settings.supabase_anon_key)
    client.postgrest.auth(access_token)
    return client
