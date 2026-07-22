"""Overrides request/response shapes (DESIGN §8.2 `overrides`, §9.6)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, model_validator


class OverrideCreate(BaseModel):
    criterion_key: str
    value: Any
    target_scope: Literal["property", "floor_plan"] = "property"
    floor_plan_id: UUID | None = None
    applicability: Literal["specific_floor_plans", "all_units"] | None = None
    note: str | None = None

    @model_validator(mode="after")
    def validate_target(self) -> OverrideCreate:
        if self.target_scope == "floor_plan":
            if self.floor_plan_id is None or self.applicability != "specific_floor_plans":
                raise ValueError(
                    "Floor Plan Override requires floor_plan_id and specific_floor_plans"
                )
        elif self.floor_plan_id is not None or self.applicability not in (None, "all_units"):
            raise ValueError("Property Override cannot target a Floor Plan")
        return self


class OverrideResponse(BaseModel):
    id: UUID
    hunt_listing_id: UUID
    criterion_key: str
    target_scope: Literal["property", "floor_plan"]
    floor_plan_id: UUID | None
    applicability: Literal["specific_floor_plans", "all_units"] | None
    value: Any
    user_id: UUID
    note: str | None
    created_at: datetime | None = None
