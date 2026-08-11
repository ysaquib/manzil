"""Rubric routes (Phase 1 plan §4.3, P1-5)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from manzil_api.dependencies import CurrentUser, UserClient
from manzil_api.hunts.dependencies import MemberHunt, WritableOwnedHunt
from manzil_api.rubric import service
from manzil_api.rubric.schemas import (
    CustomRoutingRequest,
    CustomRoutingResponse,
    RubricCriterionOut,
    RubricPut,
)

router = APIRouter(tags=["rubric"])


@router.get("/hunts/{hunt_id}/rubric", response_model=list[RubricCriterionOut])
async def get_rubric(
    hunt_id: UUID, hunt: MemberHunt, client: UserClient
) -> list[RubricCriterionOut]:
    return await service.get_rubric(client, hunt_id)


@router.put("/hunts/{hunt_id}/rubric", response_model=list[RubricCriterionOut])
async def put_rubric(
    hunt_id: UUID,
    body: RubricPut,
    hunt: WritableOwnedHunt,
    user: CurrentUser,
    client: UserClient,
) -> list[RubricCriterionOut]:
    return await service.put_rubric(client, hunt_id, user.id, body)


@router.post(
    "/hunts/{hunt_id}/rubric/custom-routing",
    response_model=CustomRoutingResponse,
)
async def classify_custom_routing(
    hunt_id: UUID,
    body: CustomRoutingRequest,
    hunt: WritableOwnedHunt,
    user: CurrentUser,
) -> CustomRoutingResponse:
    return await service.classify_custom_routing(hunt_id, user.id, body)
