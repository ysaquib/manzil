"""Rubric routes (Phase 1 plan §4.3, P1-5). Handlers stubbed until P1-5."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from manzil_api.exceptions import NotImplementedYet
from manzil_api.hunts.dependencies import OwnedHunt
from manzil_api.rubric.schemas import RubricCriterionOut, RubricPut

router = APIRouter(tags=["rubric"])


@router.get("/hunts/{hunt_id}/rubric", response_model=list[RubricCriterionOut])
async def get_rubric(hunt_id: UUID, hunt: OwnedHunt) -> list[RubricCriterionOut]:
    raise NotImplementedYet("get_rubric (P1-5)")


@router.put("/hunts/{hunt_id}/rubric", response_model=list[RubricCriterionOut])
async def put_rubric(hunt_id: UUID, body: RubricPut, hunt: OwnedHunt) -> list[RubricCriterionOut]:
    raise NotImplementedYet("put_rubric — validate, bump version, enqueue rescore (P1-5)")
