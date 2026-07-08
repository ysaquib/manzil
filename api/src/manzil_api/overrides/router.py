"""Overrides routes (Phase 1 plan §4.3, P1-8). Handler stubbed."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from manzil_api.exceptions import NotImplementedYet
from manzil_api.listings.dependencies import OwnedListing
from manzil_api.overrides.schemas import OverrideCreate, OverrideResponse

router = APIRouter(tags=["overrides"])


@router.post(
    "/listings/{listing_id}/overrides",
    response_model=OverrideResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_override(
    listing_id: UUID, body: OverrideCreate, listing: OwnedListing
) -> OverrideResponse:
    raise NotImplementedYet("create_override — insert + enqueue rescore (P1-8)")
