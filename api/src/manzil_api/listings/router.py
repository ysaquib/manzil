"""Listings routes (Phase 1 plan §4.3, P1-7/P1-11)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from manzil_api.dependencies import CurrentUser, UserClient
from manzil_api.hunts.dependencies import MemberHunt
from manzil_api.listings import service
from manzil_api.listings.dependencies import ValidListing
from manzil_api.listings.schemas import (
    ListingCreate,
    ListingResponse,
    ListingStatusPatch,
    PinsPatch,
    SourcePolicyPatch,
    UnitGroupStatePatch,
    UnitGroupStateResponse,
)

router = APIRouter(tags=["listings"])


@router.post(
    "/hunts/{hunt_id}/listings",
    response_model=ListingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_listing(
    hunt_id: UUID,
    body: ListingCreate,
    hunt: MemberHunt,
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
    hunt_id: UUID, hunt: MemberHunt, client: UserClient
) -> list[ListingResponse]:
    return await service.list_listings(client, hunt_id)


@router.delete("/listings/{listing_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_listing(
    listing_id: UUID, listing: ValidListing, user: CurrentUser, client: UserClient
) -> None:
    await service.delete_listing(client, listing_id, user.id)


@router.patch("/listings/{listing_id}/status", response_model=ListingResponse)
async def patch_status(
    listing_id: UUID,
    body: ListingStatusPatch,
    listing: ValidListing,
    user: CurrentUser,
    client: UserClient,
) -> ListingResponse:
    return await service.patch_status(client, listing, user.id, body)


@router.patch("/listings/{listing_id}/pins", response_model=ListingResponse)
async def patch_pins(
    listing_id: UUID,
    body: PinsPatch,
    listing: ValidListing,
    user: CurrentUser,
    client: UserClient,
) -> ListingResponse:
    return await service.patch_pins(client, listing, user.id, body)


@router.patch("/listings/{listing_id}/source-policy", response_model=ListingResponse)
async def patch_source_policy(
    listing_id: UUID,
    body: SourcePolicyPatch,
    listing: ValidListing,
    user: CurrentUser,
    client: UserClient,
) -> ListingResponse:
    return await service.patch_source_policy(client, listing, user.id, body)


@router.patch(
    "/listings/{listing_id}/unit-groups/{unit_group_key}/state",
    response_model=UnitGroupStateResponse,
)
async def patch_unit_group_state(
    listing_id: UUID,
    unit_group_key: str,
    body: UnitGroupStatePatch,
    listing: ValidListing,
    user: CurrentUser,
    client: UserClient,
) -> UnitGroupStateResponse:
    return await service.patch_unit_group_state(client, listing, unit_group_key, user.id, body)
