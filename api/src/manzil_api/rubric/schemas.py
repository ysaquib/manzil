"""Rubric request/response shapes — mirror the DESIGN §8.2 `rubric_criteria`
row + rubric-option contract. Options are validated against the catalog
`value_schema` via jsonschema in the service (P1-5)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class RubricOption(BaseModel):
    """One §8.2 rubric option: a value (matching the criterion's value_schema)
    and its point delta. `is_bonus` is display-only; all deltas are >= 0."""

    value: Any
    delta: float = Field(ge=0)
    label: str | None = None
    is_bonus: bool = False


class RubricCriterionIn(BaseModel):
    catalog_key: str | None = None
    custom_def: dict[str, Any] | None = None
    enabled: bool = True
    options: list[RubricOption] = Field(default_factory=list)
    unknown_delta: float = 0
    non_negotiable: dict[str, Any] | None = None
    is_bonus: bool = False
    position: int = 0


class RubricCriterionOut(RubricCriterionIn):
    id: UUID
    hunt_id: UUID


class RubricPut(BaseModel):
    criteria: list[RubricCriterionIn]
