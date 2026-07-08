"""Listings request/response shapes (DESIGN §8.2 `hunt_listings`)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

SourcePolicy = Literal["trust_link", "tier_1", "tiers_1_2", "tiers_1_2_3", "tier_1_plus_official"]


class ListingCreate(BaseModel):
    url: str = Field(min_length=1)
    # Defaulted from hunt settings when omitted (P1-7); inert until DISCOVER (P3-5).
    source_policy: SourcePolicy | None = None


class ListingResponse(BaseModel):
    id: UUID
    hunt_id: UUID
    property_id: UUID
    status: str
    source_policy: str
    pins: dict[str, Any]
    created_at: datetime | None = None


class PinsPatch(BaseModel):
    """Per-Unit-Group pinned floor plan (DESIGN §8.2 `hunt_listings.pins`)."""

    pins: dict[str, Any]
