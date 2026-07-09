"""Listings routes (Phase 1 plan §4.3, P1-7/P1-11)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from manzil_api.dependencies import CurrentUser, UserClient
from manzil_api.hunts.dependencies import OwnedHunt
from manzil_api.listings import service
from manzil_api.listings.dependencies import OwnedListing
from manzil_api.listings.schemas import ListingCreate, ListingResponse, PinsPatch

router = APIRouter(tags=["listings"])


@router.post(
    "/hunts/{hunt_id}/listings",
    response_model=ListingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_listing(
    hunt_id: UUID,
    body: ListingCreate,
    hunt: OwnedHunt,
    user: CurrentUser,
    client: UserClient,
) -> ListingResponse:
    return await service.create_listing(
        client,
        hunt_id=hunt_id,
        user_id=user.id,
        hunt_settings=hunt.get("settings") or {},
        body=body,
    )


@router.get("/hunts/{hunt_id}/listings", response_model=list[ListingResponse])
async def list_listings(
    hunt_id: UUID, hunt: OwnedHunt, client: UserClient
) -> list[ListingResponse]:
    return await service.list_listings(client, hunt_id)


@router.delete("/listings/{listing_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_listing(listing_id: UUID, listing: OwnedListing, client: UserClient) -> None:
    await service.delete_listing(client, listing_id)


@router.patch("/listings/{listing_id}/pins", response_model=ListingResponse)
async def patch_pins(
    listing_id: UUID, body: PinsPatch, listing: OwnedListing, client: UserClient
) -> ListingResponse:
    return await service.patch_pins(client, listing_id, body)
