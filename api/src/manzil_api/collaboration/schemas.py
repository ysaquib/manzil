from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from manzil_api.invites.service import MEMBER_COLOR_TOKENS


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class CommentResponse(BaseModel):
    id: UUID
    hunt_listing_id: UUID
    user_id: UUID
    body: str
    created_at: datetime
    deleted_at: datetime | None


class RatingUpsert(BaseModel):
    rating: int = Field(ge=1, le=5)


class RatingResponse(BaseModel):
    hunt_listing_id: UUID
    user_id: UUID
    rating: int


class MemberPatch(BaseModel):
    # role is deliberately constrained to member|curator: the 'owner' role only
    # moves through POST /transfer-ownership, never this endpoint.
    color: str | None = None
    display_name: str | None = None
    role: Literal["member", "curator"] | None = None

    @field_validator("color")
    @classmethod
    def validate_color(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value in MEMBER_COLOR_TOKENS:
            return value
        if len(value) == 7 and value.startswith("#"):
            try:
                int(value[1:], 16)
            except ValueError:
                pass
            else:
                return value.upper()
        raise ValueError("color must be a palette token or #RRGGBB")

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        if not 1 <= len(trimmed) <= 80:
            raise ValueError("display_name must be 1..80 non-blank characters")
        return trimmed

    @model_validator(mode="after")
    def at_least_one_field(self) -> MemberPatch:
        if not self.model_fields_set:
            raise ValueError("at least one of color, display_name, role is required")
        return self


class MemberResponse(BaseModel):
    # color is nullable in the schema (pre-P2 members were seeded without one),
    # so the response mirrors that rather than 500-ing on a legitimate null row.
    user_id: UUID
    role: str
    color: str | None = None
    display_name: str | None = None


class TransferOwnershipRequest(BaseModel):
    new_owner_id: UUID


class TransferOwnershipResponse(BaseModel):
    status: Literal["ok"]
