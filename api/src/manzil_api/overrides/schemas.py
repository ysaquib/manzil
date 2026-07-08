"""Overrides request/response shapes (DESIGN §8.2 `overrides`, §9.6)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class OverrideCreate(BaseModel):
    criterion_key: str
    value: Any
    note: str | None = None


class OverrideResponse(BaseModel):
    id: UUID
    hunt_listing_id: UUID
    criterion_key: str
    value: Any
    user_id: UUID
    note: str | None
    created_at: datetime | None = None
