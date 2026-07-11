"""Overrides service — append-only insert with attribution, then enqueue one
hunt-level rescore job (rescore-on-mutation, plan §1.7)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from manzil_api.hunts.exceptions import InsufficientRole
from manzil_api.jobs.enqueue import enqueue_rescore
from manzil_api.overrides.schemas import OverrideCreate, OverrideResponse
from supabase import Client


def _row_to_response(row: dict[str, Any]) -> OverrideResponse:
    return OverrideResponse.model_validate(row)


async def create_override(
    client: Client,
    *,
    hunt_listing_id: UUID,
    hunt_id: UUID,
    user_id: str,
    body: OverrideCreate,
) -> OverrideResponse:
    listing = (
        client.table("hunt_listings")
        .select("added_by")
        .eq("id", str(hunt_listing_id))
        .single()
        .execute()
        .data
    )
    role = (
        client.table("hunt_members")
        .select("role")
        .eq("hunt_id", str(hunt_id))
        .eq("user_id", user_id)
        .single()
        .execute()
        .data["role"]
    )
    if role == "member" and listing["added_by"] != user_id:
        raise InsufficientRole("Members may Override only their own Listings")
    response = (
        client.table("overrides")
        .insert(
            {
                "hunt_listing_id": str(hunt_listing_id),
                "criterion_key": body.criterion_key,
                "value": body.value,
                "user_id": user_id,
                "note": body.note,
            }
        )
        .execute()
    )
    row = (response.data or [None])[0]
    if row is None:
        raise RuntimeError("override insert returned no row")
    await enqueue_rescore(client, hunt_id)
    return _row_to_response(row)
