"""Listings request/response shapes (DESIGN §8.2 `hunt_listings`)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

SourcePolicy = Literal["trust_link", "tier_1", "tiers_1_2", "tiers_1_2_3", "tier_1_plus_official"]
InterestStatus = Literal[
    "interested",
    "not_interested",
    "applied",
    "application_rejected",
    "application_withdrawn",
    "offer_received",
    "offer_accepted",
    "offer_declined",
    "offer_rescinded",
    "unavailable",
]


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
    # Set when ingest/refresh found no available floor plans (§8.2); null while
    # pending or scored. Drives the dimmed, null-score Overview row.
    unavailable_at: datetime | None = None


class ListingStatusPatch(BaseModel):
    """Archive / restore (§8.2 `hunt_listings.status`) — the soft-delete pair."""

    status: Literal["active", "archived"]


class PinsPatch(BaseModel):
    """Per-Unit-Group pinned floor plan (DESIGN §8.2 `hunt_listings.pins`)."""

    pins: dict[str, Any]


class UnitGroupStatePatch(BaseModel):
    interest_status: InterestStatus | None
    visited: bool


class UnitGroupStateResponse(UnitGroupStatePatch):
    hunt_listing_id: UUID
    unit_group_key: str
    updated_by: UUID
    updated_at: datetime
