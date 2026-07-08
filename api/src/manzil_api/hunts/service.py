"""Hunts service layer — wraps supabase-py/PostgREST (IMPLEMENTATION §2; no ORM).

Scaffolding: `get_hunt_row` is implemented because the auth dependency chain
(`valid_hunt_id` → `require_owner`) needs it now. The create/list/patch write
paths are stubbed for P1-5.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from supabase import Client


async def get_hunt_row(client: Client, hunt_id: UUID) -> dict[str, Any] | None:
    """Fetch one hunt by id via the caller-authenticated client, or None."""
    response = client.table("hunts").select("*").eq("id", str(hunt_id)).limit(1).execute()
    rows = response.data or []
    return rows[0] if rows else None
