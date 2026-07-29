"""Utility-inclusion correction routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from manzil_api.dependencies import CurrentUser, UserClient
from manzil_api.listings.dependencies import ValidListing
from manzil_api.utilities import service
from manzil_api.utilities.schemas import (
    UtilityName,
    UtilityOverrideResponse,
    UtilityOverrideUpsert,
)

router = APIRouter(tags=["utilities"])


@router.put("/listings/{listing_id}/utilities/{utility}", response_model=UtilityOverrideResponse)
async def upsert_utility_override(
    listing_id: UUID,
    utility: UtilityName,
    body: UtilityOverrideUpsert,
    listing: ValidListing,
    user: CurrentUser,
    client: UserClient,
) -> UtilityOverrideResponse:
    return await service.upsert_utility_override(
        client,
        hunt_listing_id=listing_id,
        hunt_id=UUID(str(listing["hunt_id"])),
        user_id=user.id,
        utility=utility,
        body=body,
    )
