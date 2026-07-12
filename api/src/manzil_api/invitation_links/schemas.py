from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, Field, model_validator


def _normalize_name(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("name must be a string or null")
    trimmed = value.strip()
    return trimmed or None


NormalizedName = Annotated[str | None, BeforeValidator(_normalize_name)]


class InvitationLinkCreate(BaseModel):
    name: NormalizedName = Field(default=None, max_length=80)
    max_uses: int | None = Field(default=None, ge=1)
    expires_at: datetime | None = None


class InvitationLinkPatch(BaseModel):
    name: NormalizedName = Field(default=None, max_length=80)
    max_uses: int | None = Field(default=None, ge=1)
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def require_field_and_expiration(self) -> InvitationLinkPatch:
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        if "expires_at" in self.model_fields_set and self.expires_at is None:
            raise ValueError("expires_at cannot be null")
        return self


class InvitationLinkJoinRecord(BaseModel):
    user_id: UUID
    display_name: str
    joined_at: datetime


class InvitationLinkResponse(BaseModel):
    id: UUID
    hunt_id: UUID
    created_at: datetime
    name: str | None
    max_uses: int | None
    expires_at: datetime
    use_count: int
    status: Literal["active", "expired", "exhausted"]
    link: str
    joins: list[InvitationLinkJoinRecord]


class InvitationLinkJoined(BaseModel):
    hunt_id: UUID
