"""Utility-override request/response shapes (DESIGN §9.5)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

UtilityName = Literal["electric", "gas", "water", "sewer", "cooling", "heat", "trash"]


class UtilityOverrideUpsert(BaseModel):
    """Both values null appends a revert tombstone for this utility."""

    included: bool | None
    monthly_amount: float | None = Field(default=None, ge=0)
    note: str | None = None


class UtilityOverrideResponse(BaseModel):
    id: UUID
    hunt_listing_id: UUID
    utility: UtilityName
    included: bool | None
    monthly_amount: float | None
    user_id: UUID
    note: str | None
    created_at: datetime | None = None
