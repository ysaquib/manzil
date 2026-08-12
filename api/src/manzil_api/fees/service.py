"""Fees service — upsert on `(hunt_listing_id, fee_slot)`, then enqueue one
hunt-level rescore job (rescore-on-mutation, plan §1.7)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from manzil_api.fees.schemas import FeeEntryResponse, FeeEntryUpsert
from manzil_api.hunts.exceptions import InsufficientRole
from manzil_api.jobs.enqueue import enqueue_rescore
from supabase import Client


def _row_to_response(row: dict[str, Any]) -> FeeEntryResponse:
    return FeeEntryResponse.model_validate(row)


async def upsert_fee(
    client: Client,
    *,
    hunt_listing_id: UUID,
    hunt_id: UUID,
    user_id: str,
    fee_slot: str,
    body: FeeEntryUpsert,
    authorized_admin: bool = False,
) -> FeeEntryResponse:
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
        raise InsufficientRole("Members may edit fees only on their own Listings")
    response = (
        client.table("fee_checklist")
        .upsert(
            {
                "hunt_listing_id": str(hunt_listing_id),
                "fee_slot": fee_slot,
                "amount": body.amount,
                "value_state": body.value_state.value,
                "entered_by": user_id,
                "evidence_ref": body.evidence_ref,
                "counted": body.counted,
                "required": body.required,
                "refundable": body.refundable,
                "credited_amount": body.credited_amount,
                # Bump on re-entry: the INSERT default only fires on first insert,
                # so an upsert of an existing (hunt_listing_id, fee_slot) must set
                # updated_at explicitly or it would freeze at the original time.
                "updated_at": datetime.now(UTC).isoformat(),
            },
            on_conflict="hunt_listing_id,fee_slot",
        )
        .execute()
    )
    row = (response.data or [None])[0]
    if row is None:
        raise RuntimeError("fee upsert returned no row")
    await enqueue_rescore(client, hunt_id, requested_by=user_id)
    return _row_to_response(row)
