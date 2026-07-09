"""Fees service — upsert on `(hunt_listing_id, fee_slot)`, then enqueue one
hunt-level rescore job (rescore-on-mutation, plan §1.7)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from manzil_api.fees.schemas import FeeEntryResponse, FeeEntryUpsert
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
) -> FeeEntryResponse:
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
            },
            on_conflict="hunt_listing_id,fee_slot",
        )
        .execute()
    )
    row = (response.data or [None])[0]
    if row is None:
        raise RuntimeError("fee upsert returned no row")
    await enqueue_rescore(client, hunt_id)
    return _row_to_response(row)
