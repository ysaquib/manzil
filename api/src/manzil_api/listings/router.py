"""Listings routes (Phase 1 plan §4.3, P1-7/P1-11). Handlers stubbed.

`PATCH /listings/{id}/pins` is folded in here per the plan (pins live on
`hunt_listings`, not their own DESIGN §5.1 route — a Phase 1 fill-in).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from manzil_api.exceptions import NotImplementedYet
from manzil_api.hunts.dependencies import OwnedHunt
from manzil_api.listings.dependencies import OwnedListing
from manzil_api.listings.schemas import (
    ListingCreate,
    ListingResponse,
    PinsPatch,
)

router = APIRouter(tags=["listings"])


@router.post(
    "/hunts/{hunt_id}/listings",
    response_model=ListingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_listing(hunt_id: UUID, body: ListingCreate, hunt: OwnedHunt) -> ListingResponse:
    raise NotImplementedYet("create_listing — fresh property + ingest job (P1-7)")


@router.get("/hunts/{hunt_id}/listings", response_model=list[ListingResponse])
async def list_listings(hunt_id: UUID, hunt: OwnedHunt) -> list[ListingResponse]:
    raise NotImplementedYet("list_listings (P1-7)")


@router.delete("/listings/{listing_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_listing(listing_id: UUID, listing: OwnedListing) -> None:
    raise NotImplementedYet("delete_listing (P1-7)")


@router.patch("/listings/{listing_id}/pins", response_model=ListingResponse)
async def patch_pins(listing_id: UUID, body: PinsPatch, listing: OwnedListing) -> ListingResponse:
    raise NotImplementedYet("patch_pins (P1-11)")
