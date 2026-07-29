"""Fee-checklist request/response shapes (DESIGN §8.2 `fee_checklist`, §9.5)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from manzil_shared.models import ValueState
from pydantic import BaseModel, Field


class FeeEntryUpsert(BaseModel):
    """One fee-slot edit from the consolidated Cost & fees section (§9.5).

    The three flags are tri-state and stay `None` unless a human decides:
    `counted` NULL means the machine default (counted when an amount is known),
    and `required`/`refundable` NULL mean the Source never said — which is what
    keeps a move-in total honestly Incomplete instead of quietly optimistic.
    """

    amount: float | None = None
    value_state: ValueState = ValueState.UNKNOWN
    evidence_ref: str | None = None
    counted: bool | None = None
    required: bool | None = None
    refundable: bool | None = None
    credited_amount: float | None = Field(default=None, ge=0)


class FeeEntryResponse(BaseModel):
    hunt_listing_id: UUID
    fee_slot: str
    amount: float | None
    value_state: ValueState
    entered_by: UUID | None
    evidence_ref: str | None
    updated_at: datetime | None = None
    counted: bool | None = None
    required: bool | None = None
    refundable: bool | None = None
    credited_amount: float | None = None
