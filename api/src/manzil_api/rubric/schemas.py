"""Rubric request/response shapes — mirror the DESIGN §8.2 `rubric_criteria`
row + rubric-option contract. Options are validated against the catalog
`value_schema` via jsonschema in the service (P1-5)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from manzil_shared.models import NonNegotiable, RubricOption
from pydantic import BaseModel, Field


class RubricCriterionIn(BaseModel):
    catalog_key: str | None = None
    custom_def: dict[str, Any] | None = None
    enabled: bool = True
    options: list[RubricOption] = Field(default_factory=list)
    unknown_delta: float = 0
    non_negotiable: NonNegotiable | None = None
    is_bonus: bool = False
    position: int = 0


class RubricCriterionOut(RubricCriterionIn):
    id: UUID
    hunt_id: UUID


class RubricPut(BaseModel):
    criteria: list[RubricCriterionIn]
