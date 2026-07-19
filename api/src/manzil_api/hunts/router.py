"""Hunts routes (Phase 1 plan §4.3, P1-5)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from manzil_api.dependencies import CurrentUser, UserClient
from manzil_api.hunts import service
from manzil_api.hunts.dependencies import CuratedHunt, MemberHunt, OwnedHunt
from manzil_api.hunts.schemas import (
    HuntCreate,
    HuntResponse,
    HuntSettingsPatch,
    HuntUpdate,
    SharedFiltersPut,
    SharedFiltersResponse,
)

router = APIRouter(tags=["hunts"])


@router.post("/hunts", response_model=HuntResponse, status_code=status.HTTP_201_CREATED)
async def create_hunt(body: HuntCreate, user: CurrentUser, client: UserClient) -> HuntResponse:
    return await service.create_hunt(client, user.id, body)


@router.get("/hunts", response_model=list[HuntResponse])
async def list_hunts(user: CurrentUser, client: UserClient) -> list[HuntResponse]:
    return await service.list_hunts(client, user.id)


@router.get("/hunts/{hunt_id}", response_model=HuntResponse)
async def get_hunt(hunt_id: UUID, hunt: MemberHunt) -> HuntResponse:
    return HuntResponse.model_validate(hunt)


@router.patch("/hunts/{hunt_id}", response_model=HuntResponse)
async def patch_hunt(
    hunt_id: UUID, body: HuntUpdate, hunt: OwnedHunt, client: UserClient
) -> HuntResponse:
    return await service.patch_hunt(client, hunt_id, body)


@router.put("/hunts/{hunt_id}/shared-filters", response_model=SharedFiltersResponse)
async def put_shared_filters(
    hunt_id: UUID, body: SharedFiltersPut, hunt: CuratedHunt, user: CurrentUser, client: UserClient
) -> SharedFiltersResponse:
    return await service.put_shared_filters(client, hunt_id, user.id, body)


@router.patch("/hunts/{hunt_id}/settings", response_model=HuntResponse)
async def patch_hunt_settings(
    hunt_id: UUID, body: HuntSettingsPatch, hunt: OwnedHunt, client: UserClient
) -> HuntResponse:
    return await service.patch_settings(client, hunt_id, body)
