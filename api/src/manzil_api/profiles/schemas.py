from __future__ import annotations

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, field_validator, model_validator

from manzil_api.invites.service import MEMBER_COLOR_TOKENS


class ProfileUpsert(BaseModel):
    default_display_name: str
    # Optional so onboarding's name-only PUT never touches the color; the
    # profile page sends both. Same vocabulary as MemberPatch.color. Explicit
    # null is rejected — the DB assigns a palette token on insert when omitted.
    default_color: str | None = None

    @field_validator("default_display_name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not 1 <= len(value) <= 80:
            raise ValueError("default_display_name must be 1..80 non-blank characters")
        return value

    @field_validator("default_color")
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
        raise ValueError("default_color must be a palette token or #RRGGBB")

    @model_validator(mode="after")
    def reject_explicit_null_color(self) -> Self:
        if "default_color" in self.model_fields_set and self.default_color is None:
            raise ValueError("default_color cannot be null")
        return self


class ProfileResponse(BaseModel):
    user_id: UUID
    default_display_name: str
    default_color: str
    created_at: datetime
    updated_at: datetime
