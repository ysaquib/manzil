"""Hunts request/response shapes. Field lists mirror the DESIGN §8.2 `hunts`
row; `settings` is validated app-side against the §8.2 hunt-settings contract
(P1-5), not by a DB check."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class HuntCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    domain: Literal["rent", "buy"] = "rent"


class HuntUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    archived: bool | None = None


class HuntSettingsPatch(BaseModel):
    """Partial update of the §8.2 hunt-settings contract. Scoring-affecting keys
    reuse the bump-and-rescore path (P1-5); every key is defaulted server-side."""

    settings: dict[str, Any]


class SharedFiltersPut(BaseModel):
    """Hunt-wide Overview filters (§13.2, §20 2026-07-19). View state, not
    settings: an opaque-to-the-API object the frontend sanitizes on read, so
    filter-set growth never needs an API change."""

    filters: dict[str, Any]


class SharedFiltersResponse(BaseModel):
    hunt_id: UUID
    filters: dict[str, Any]
    updated_by: UUID
    updated_at: datetime


class HuntResponse(BaseModel):
    id: UUID
    name: str
    owner_id: UUID
    domain: str
    rubric_version: int
    settings: dict[str, Any]
    archived_at: datetime | None
    created_at: datetime | None = None
