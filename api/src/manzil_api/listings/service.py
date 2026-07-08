"""Listings service — wraps supabase-py (IMPLEMENTATION §2).

Scaffolding: `get_listing_row` backs the `valid_listing_id` dependency; the
create/delete/pins write paths are stubbed for P1-7/P1-11.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from supabase import Client


async def get_listing_row(client: Client, listing_id: UUID) -> dict[str, Any] | None:
    response = (
        client.table("hunt_listings").select("*").eq("id", str(listing_id)).limit(1).execute()
    )
    rows = response.data or []
    return rows[0] if rows else None
