from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from manzil_api.dependencies import CurrentUser, SettingsDep, UserClient
from manzil_api.hunts.dependencies import OwnedHunt, WritableOwnedHunt
from manzil_api.invitation_links import service
from manzil_api.invitation_links.schemas import (
    InvitationLinkCreate,
    InvitationLinkJoined,
    InvitationLinkPatch,
    InvitationLinkResponse,
)

router = APIRouter(tags=["invitation-links"])


@router.post(
    "/hunts/{hunt_id}/invitation-links",
    response_model=InvitationLinkResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_invitation_link(
    hunt_id: UUID,
    body: InvitationLinkCreate,
    hunt: WritableOwnedHunt,
    user: CurrentUser,
    client: UserClient,
    settings: SettingsDep,
) -> InvitationLinkResponse:
    return await service.create_invitation_link(client, settings, hunt_id, user.id, body)


@router.get("/hunts/{hunt_id}/invitation-links", response_model=list[InvitationLinkResponse])
async def list_invitation_links(
    hunt_id: UUID, hunt: OwnedHunt, client: UserClient, settings: SettingsDep
) -> list[InvitationLinkResponse]:
    return await service.list_invitation_links(client, settings.frontend_url, hunt_id)


@router.patch("/invitation-links/{invitation_link_id}", response_model=InvitationLinkResponse)
async def patch_invitation_link(
    invitation_link_id: UUID,
    body: InvitationLinkPatch,
    user: CurrentUser,
    client: UserClient,
    settings: SettingsDep,
) -> InvitationLinkResponse:
    return await service.patch_invitation_link(
        client, settings.frontend_url, invitation_link_id, body
    )


@router.delete("/invitation-links/{invitation_link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_invitation_link(
    invitation_link_id: UUID, user: CurrentUser, client: UserClient
) -> None:
    await service.delete_invitation_link(client, invitation_link_id, user.id)


@router.post("/invitation-links/{token}/join", response_model=InvitationLinkJoined)
async def join_invitation_link(
    token: str, user: CurrentUser, settings: SettingsDep
) -> InvitationLinkJoined:
    return await service.join_invitation_link(settings, token, user.id)
