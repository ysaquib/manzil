from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from manzil_api.collaboration import service
from manzil_api.collaboration.schemas import (
    CommentCreate,
    CommentResponse,
    CommentUpdate,
    MemberPatch,
    MemberResponse,
    RatingResponse,
    RatingUpsert,
    TransferOwnershipRequest,
    TransferOwnershipResponse,
)
from manzil_api.dependencies import CurrentUser, SettingsDep, UserClient
from manzil_api.hunts.dependencies import MemberHunt, OwnedHunt
from manzil_api.listings.dependencies import ValidListing

router = APIRouter(tags=["collaboration"])


@router.post("/listings/{listing_id}/comments", response_model=CommentResponse, status_code=201)
async def create_comment(
    listing_id: UUID,
    body: CommentCreate,
    listing: ValidListing,
    user: CurrentUser,
    client: UserClient,
) -> CommentResponse:
    return await service.create_comment(client, listing, user.id, body)


@router.patch("/comments/{comment_id}", response_model=CommentResponse)
async def update_comment(
    comment_id: UUID, body: CommentUpdate, user: CurrentUser, client: UserClient
) -> CommentResponse:
    return await service.update_comment(client, comment_id, user.id, body)


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(comment_id: UUID, user: CurrentUser, client: UserClient) -> None:
    await service.delete_comment(client, comment_id, user.id)


@router.put(
    "/listings/{listing_id}/unit-groups/{unit_group_key}/rating",
    response_model=RatingResponse,
)
async def upsert_rating(
    listing_id: UUID,
    unit_group_key: str,
    body: RatingUpsert,
    listing: ValidListing,
    user: CurrentUser,
    client: UserClient,
) -> RatingResponse:
    return await service.upsert_rating(client, listing, unit_group_key, user.id, body)


@router.delete(
    "/listings/{listing_id}/unit-groups/{unit_group_key}/rating",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_rating(
    listing_id: UUID,
    unit_group_key: str,
    listing: ValidListing,
    user: CurrentUser,
    client: UserClient,
) -> None:
    await service.delete_rating(client, listing, unit_group_key, user.id)


@router.get("/hunts/{hunt_id}/members", response_model=list[MemberResponse])
async def list_members(hunt_id: UUID, hunt: MemberHunt, client: UserClient) -> list[MemberResponse]:
    return await service.list_members(client, hunt_id)


@router.patch("/hunts/{hunt_id}/members/{target_user_id}", response_model=MemberResponse)
async def patch_member(
    hunt_id: UUID,
    target_user_id: UUID,
    body: MemberPatch,
    hunt: MemberHunt,
    user: CurrentUser,
    client: UserClient,
) -> MemberResponse:
    return await service.patch_member(client, hunt_id, target_user_id, user.id, body)


@router.delete("/hunts/{hunt_id}/members/{target_user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    hunt_id: UUID, target_user_id: UUID, hunt: OwnedHunt, client: UserClient
) -> None:
    await service.remove_member(client, hunt_id, target_user_id)


@router.post("/hunts/{hunt_id}/transfer-ownership", response_model=TransferOwnershipResponse)
async def transfer_ownership(
    hunt_id: UUID,
    body: TransferOwnershipRequest,
    hunt: OwnedHunt,
    settings: SettingsDep,
) -> TransferOwnershipResponse:
    return await service.transfer_ownership(settings, hunt_id, body.new_owner_id)
