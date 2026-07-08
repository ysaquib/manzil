"""Fee-checklist request/response shapes (DESIGN §8.2 `fee_checklist`, §9.5)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from manzil_shared.models import ValueState
from pydantic import BaseModel


class FeeEntryUpsert(BaseModel):
    amount: float | None = None
    value_state: ValueState = ValueState.UNKNOWN
    evidence_ref: str | None = None


class FeeEntryResponse(BaseModel):
    id: UUID
    hunt_listing_id: UUID
    fee_slot: str
    amount: float | None
    value_state: ValueState
    entered_by: UUID | None
    evidence_ref: str | None
    updated_at: datetime | None = None
