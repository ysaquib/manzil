"""Listings request/response shapes (DESIGN §8.2 `hunt_listings`)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

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
    single_source_reason: Literal["trust_link", "discover_exhausted", "discover_failed"] | None = (
        None
    )
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


class SourcePolicyPatch(BaseModel):
    """Change one Listing's cross-check policy (DESIGN §10.7, P3-5)."""

    source_policy: SourcePolicy


RefreshClass = Literal["pricing", "listing_details", "images", "reviews", "location"]
REFRESH_CLASS_ORDER: tuple[RefreshClass, ...] = (
    "pricing",
    "listing_details",
    "images",
    "reviews",
    "location",
)


class RefreshRequest(BaseModel):
    """P3-12 refresh-class selection. Omission means every mutable class."""

    fields: list[RefreshClass] | None = None

    @field_validator("fields")
    @classmethod
    def fields_are_non_empty(cls, value: list[RefreshClass] | None) -> list[RefreshClass] | None:
        if value == []:
            raise ValueError("fields must contain at least one refresh class")
        return value

    @classmethod
    def normalized_fields(cls, fields: list[RefreshClass] | None) -> list[RefreshClass]:
        selected: list[RefreshClass] = list(REFRESH_CLASS_ORDER[:-1] if fields is None else fields)
        if not selected:
            raise ValueError("fields must contain at least one refresh class")
        chosen = set(selected)
        return [refresh_class for refresh_class in REFRESH_CLASS_ORDER if refresh_class in chosen]


class UnitGroupStatePatch(BaseModel):
    interest_status: InterestStatus | None
    visited: bool


class UnitGroupStateResponse(UnitGroupStatePatch):
    hunt_listing_id: UUID
    unit_group_key: str
    updated_by: UUID
    updated_at: datetime
