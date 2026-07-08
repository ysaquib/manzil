"""Hunts routes (Phase 1 plan §4.3, P1-5).

Scaffolding: routes are declared with their final method/path/response_model so
OpenAPI codegen has the real surface; handler bodies raise `NotImplementedYet`
until P1-5 fills them in. The auth dependency chain is already wired.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from manzil_api.dependencies import CurrentUser
from manzil_api.exceptions import NotImplementedYet
from manzil_api.hunts.dependencies import OwnedHunt
from manzil_api.hunts.schemas import HuntCreate, HuntResponse, HuntSettingsPatch, HuntUpdate

router = APIRouter(tags=["hunts"])


@router.post("/hunts", response_model=HuntResponse, status_code=status.HTTP_201_CREATED)
async def create_hunt(body: HuntCreate, user: CurrentUser) -> HuntResponse:
    raise NotImplementedYet("create_hunt (P1-5)")


@router.get("/hunts", response_model=list[HuntResponse])
async def list_hunts(user: CurrentUser) -> list[HuntResponse]:
    raise NotImplementedYet("list_hunts (P1-5)")


@router.get("/hunts/{hunt_id}", response_model=HuntResponse)
async def get_hunt(hunt_id: UUID, hunt: OwnedHunt) -> HuntResponse:
    raise NotImplementedYet("get_hunt (P1-5)")


@router.patch("/hunts/{hunt_id}", response_model=HuntResponse)
async def patch_hunt(hunt_id: UUID, body: HuntUpdate, hunt: OwnedHunt) -> HuntResponse:
    raise NotImplementedYet("patch_hunt (P1-5)")


@router.patch("/hunts/{hunt_id}/settings", response_model=HuntResponse)
async def patch_hunt_settings(
    hunt_id: UUID, body: HuntSettingsPatch, hunt: OwnedHunt
) -> HuntResponse:
    raise NotImplementedYet("patch_hunt_settings — bump-and-rescore on scoring keys (P1-5)")
