from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from manzil_api.dependencies import CurrentUser, DbPool, SettingsDep, UserClient
from manzil_api.hunts.dependencies import OwnedHunt
from manzil_api.invites import service
from manzil_api.invites.schemas import InviteAccepted, InviteCreate, InviteResponse

router = APIRouter(tags=["invites"])


@router.post("/hunts/{hunt_id}/invites", response_model=InviteResponse, status_code=201)
async def create_invite(
    hunt_id: UUID,
    body: InviteCreate,
    hunt: OwnedHunt,
    user: CurrentUser,
    client: UserClient,
    settings: SettingsDep,
) -> InviteResponse:
    return await service.create_invite(client, settings, hunt_id, user.id, body)


@router.get("/hunts/{hunt_id}/invites", response_model=list[InviteResponse])
async def list_invites(
    hunt_id: UUID, hunt: OwnedHunt, client: UserClient, settings: SettingsDep, pool: DbPool
) -> list[InviteResponse]:
    return await service.list_invites(client, settings.frontend_url, hunt_id, pool)


@router.post("/invites/{invite_id}/resend", response_model=InviteResponse)
async def resend_invite(
    invite_id: UUID,
    user: CurrentUser,
    client: UserClient,
    settings: SettingsDep,
    pool: DbPool,
) -> InviteResponse:
    return await service.resend_invite(client, pool, settings.frontend_url, invite_id, user.id)


@router.delete("/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(invite_id: UUID, user: CurrentUser, client: UserClient) -> None:
    await service.revoke_invite(client, invite_id)


@router.post("/invites/{token}/accept", response_model=InviteAccepted)
async def accept_invite(token: str, user: CurrentUser, settings: SettingsDep) -> InviteAccepted:
    return await service.accept_invite(settings, token, user.id)
