"""Fees routes (Phase 1 plan §4.3, P1-8)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from manzil_api.dependencies import CurrentUser, UserClient
from manzil_api.fees import service
from manzil_api.fees.schemas import FeeEntryResponse, FeeEntryUpsert
from manzil_api.listings.dependencies import OwnedListing

router = APIRouter(tags=["fees"])


@router.put("/listings/{listing_id}/fees/{fee_slot}", response_model=FeeEntryResponse)
async def upsert_fee(
    listing_id: UUID,
    fee_slot: str,
    body: FeeEntryUpsert,
    listing: OwnedListing,
    user: CurrentUser,
    client: UserClient,
) -> FeeEntryResponse:
    return await service.upsert_fee(
        client,
        hunt_listing_id=listing_id,
        hunt_id=UUID(str(listing["hunt_id"])),
        user_id=user.id,
        fee_slot=fee_slot,
        body=body,
    )
