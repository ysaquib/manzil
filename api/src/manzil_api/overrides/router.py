"""Overrides routes (Phase 1 plan §4.3, P1-8)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from manzil_api.dependencies import CurrentUser, UserClient
from manzil_api.listings.dependencies import OwnedListing
from manzil_api.overrides import service
from manzil_api.overrides.schemas import OverrideCreate, OverrideResponse

router = APIRouter(tags=["overrides"])


@router.post(
    "/listings/{listing_id}/overrides",
    response_model=OverrideResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_override(
    listing_id: UUID,
    body: OverrideCreate,
    listing: OwnedListing,
    user: CurrentUser,
    client: UserClient,
) -> OverrideResponse:
    return await service.create_override(
        client,
        hunt_listing_id=listing_id,
        hunt_id=UUID(str(listing["hunt_id"])),
        user_id=user.id,
        body=body,
    )
