"""Listings dependency chain (Phase 1 plan §4.1).

`valid_listing_id` resolves the listing and enforces the Phase 1 ownership
stand-in via its parent hunt (owner-only), mirroring `hunts.require_owner`.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends

from manzil_api.dependencies import CurrentUser, get_user_client
from manzil_api.hunts import service as hunts_service
from manzil_api.hunts.exceptions import NotHuntOwner
from manzil_api.listings import service
from manzil_api.listings.exceptions import ListingNotFound
from supabase import Client

Listing = dict[str, Any]


async def valid_listing_id(
    listing_id: UUID,
    user: CurrentUser,
    client: Annotated[Client, Depends(get_user_client)],
) -> Listing:
    listing = await service.get_listing_row(client, listing_id)
    if listing is None:
        raise ListingNotFound(f"Listing {listing_id} not found")
    hunt = await hunts_service.get_hunt_row(client, listing["hunt_id"])
    if hunt is None or hunt.get("owner_id") != user.id:
        raise NotHuntOwner("Only the hunt owner may perform this action")
    return listing


OwnedListing = Annotated[Listing, Depends(valid_listing_id)]
