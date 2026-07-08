"""Fees routes (Phase 1 plan §4.3, P1-8). Handler stubbed."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from manzil_api.exceptions import NotImplementedYet
from manzil_api.fees.schemas import FeeEntryResponse, FeeEntryUpsert
from manzil_api.listings.dependencies import OwnedListing

router = APIRouter(tags=["fees"])


@router.put("/listings/{listing_id}/fees/{fee_slot}", response_model=FeeEntryResponse)
async def upsert_fee(
    listing_id: UUID, fee_slot: str, body: FeeEntryUpsert, listing: OwnedListing
) -> FeeEntryResponse:
    raise NotImplementedYet("upsert_fee — upsert + enqueue rescore (P1-8)")
