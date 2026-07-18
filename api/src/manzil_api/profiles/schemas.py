from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, field_validator


class ProfileUpsert(BaseModel):
    default_display_name: str

    @field_validator("default_display_name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not 1 <= len(value) <= 80:
            raise ValueError("default_display_name must be 1..80 non-blank characters")
        return value


class ProfileResponse(BaseModel):
    user_id: UUID
    default_display_name: str
    created_at: datetime
    updated_at: datetime
