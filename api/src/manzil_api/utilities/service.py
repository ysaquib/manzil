"""Append-only, independently revertible utility-inclusion overrides."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from manzil_api.hunts.exceptions import InsufficientRole
from manzil_api.jobs.enqueue import enqueue_rescore
from manzil_api.utilities.schemas import (
    UtilityName,
    UtilityOverrideResponse,
    UtilityOverrideUpsert,
)
from supabase import Client


async def upsert_utility_override(
    client: Client,
    *,
    hunt_listing_id: UUID,
    hunt_id: UUID,
    user_id: str,
    utility: UtilityName,
    body: UtilityOverrideUpsert,
    authorized_admin: bool = False,
) -> UtilityOverrideResponse:
    listing = (
        client.table("hunt_listings")
        .select("added_by")
        .eq("id", str(hunt_listing_id))
        .single()
        .execute()
        .data
    )
    role = None
    if not authorized_admin:
        role = (
            client.table("hunt_members")
            .select("role")
            .eq("hunt_id", str(hunt_id))
            .eq("user_id", user_id)
            .single()
            .execute()
            .data["role"]
        )
    if not authorized_admin and role == "member" and listing["added_by"] != user_id:
        raise InsufficientRole("Members may edit utilities only on their own Listings")
    response = (
        client.table("utility_overrides")
        .insert(
            {
                "hunt_listing_id": str(hunt_listing_id),
                "utility": utility,
                "included": body.included,
                "monthly_amount": body.monthly_amount,
                "user_id": user_id,
                "note": body.note,
            }
        )
        .execute()
    )
    row: dict[str, Any] | None = (response.data or [None])[0]
    if row is None:
        raise RuntimeError("utility override insert returned no row")
    await enqueue_rescore(client, hunt_id)
    return UtilityOverrideResponse.model_validate(row)
