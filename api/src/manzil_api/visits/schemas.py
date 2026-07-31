"""Visit request/response shapes (DESIGN §9.7, VC-1)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    Field,
    computed_field,
    field_serializer,
    field_validator,
    model_validator,
)

VisitState = Literal["planned", "in_progress", "completed", "cancelled"]

_MAX_UNITS_PER_VISIT = 40


def _clean_label(value: str) -> str:
    trimmed = value.strip()
    if not 1 <= len(trimmed) <= 80:
        raise ValueError("label must be 1..80 non-blank characters")
    return trimmed


def _validate_baths(value: Decimal) -> Decimal:
    if value < 0 or value > 20:
        raise ValueError("baths must be between 0 and 20")
    if (value * 2) != (value * 2).to_integral_value():
        raise ValueError("baths must be in 0.5 steps")
    return value.quantize(Decimal("0.1"))


class VisitUnitInput(BaseModel):
    """One door you expect to walk through.

    `label` is always human-supplied — there is no advertised unit list to pick
    from (DESIGN §9.7). `floor_plan_id` links it to a marketed layout when it
    maps to one; otherwise `beds`/`baths` describe it. Exactly one of the two
    paths must be usable, which the service resolves into concrete beds/baths.
    """

    label: str = Field(min_length=1, max_length=80)
    floor_plan_id: UUID | None = None
    beds: int | None = Field(default=None, ge=0, le=20)
    baths: Decimal | None = Field(default=None, ge=0, le=20)
    display_order: int = Field(default=0, ge=0, le=10_000)

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str) -> str:
        return _clean_label(value)

    @field_validator("baths")
    @classmethod
    def validate_baths(cls, value: Decimal | None) -> Decimal | None:
        return None if value is None else _validate_baths(value)

    @model_validator(mode="after")
    def needs_a_shape(self) -> VisitUnitInput:
        if self.floor_plan_id is None and (self.beds is None or self.baths is None):
            raise ValueError("provide floor_plan_id, or both beds and baths")
        return self


class VisitUnitPatch(BaseModel):
    label: str | None = None
    display_order: int | None = Field(default=None, ge=0, le=10_000)

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str | None) -> str | None:
        return None if value is None else _clean_label(value)

    @model_validator(mode="after")
    def at_least_one_field(self) -> VisitUnitPatch:
        if not self.model_fields_set:
            raise ValueError("at least one of label, display_order is required")
        return self


class VisitCreate(BaseModel):
    property_id: UUID
    scheduled_for: datetime | None = None
    prefilled_from: UUID | None = None
    units: list[VisitUnitInput] = Field(default_factory=list, max_length=_MAX_UNITS_PER_VISIT)

    @model_validator(mode="after")
    def unique_labels(self) -> VisitCreate:
        labels = [unit.label.casefold() for unit in self.units]
        if len(labels) != len(set(labels)):
            raise ValueError("unit labels must be unique within a visit")
        return self


class VisitPatch(BaseModel):
    """Lifecycle transitions, expressed as the timestamps state derives from.

    Deliberately actions rather than raw timestamps: `started_at` is the server's
    clock, not the client's, so a phone with a skewed clock cannot record a tour
    that started tomorrow.
    """

    action: Literal["start", "end", "reopen", "cancel", "reinstate", "reschedule"] | None = None
    scheduled_for: datetime | None = None
    cancel_reason: str | None = Field(default=None, max_length=500)

    @field_validator("cancel_reason")
    @classmethod
    def clean_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None

    @model_validator(mode="after")
    def coherent(self) -> VisitPatch:
        if self.action is None and "scheduled_for" not in self.model_fields_set:
            raise ValueError("provide an action, or scheduled_for")
        if self.action == "reschedule" and self.scheduled_for is None:
            raise ValueError("reschedule requires scheduled_for")
        if self.cancel_reason is not None and self.action != "cancel":
            raise ValueError("cancel_reason is only valid with action=cancel")
        return self


class VisitUnitResponse(BaseModel):
    id: UUID
    visit_id: UUID
    label: str
    floor_plan_id: UUID | None
    beds: int
    baths: Decimal
    unit_group_key: str
    display_order: int
    created_by: UUID
    created_at: datetime

    @field_serializer("baths")
    def serialize_baths(self, value: Decimal) -> float:
        return float(value)


class VisitResponse(BaseModel):
    id: UUID
    hunt_id: UUID
    property_id: UUID
    created_by: UUID
    scheduled_for: datetime | None
    started_at: datetime | None
    ended_at: datetime | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    template_version: int
    prefilled_from: UUID | None
    created_at: datetime
    units: list[VisitUnitResponse] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def state(self) -> VisitState:
        """Derived, never stored (DESIGN §9.7). Cancellation outranks everything:
        a cancelled tour that had already started is still cancelled."""
        if self.cancelled_at is not None:
            return "cancelled"
        if self.ended_at is not None:
            return "completed"
        if self.started_at is not None:
            return "in_progress"
        return "planned"


class VisitCustomItemCreate(BaseModel):
    section_key: str = Field(min_length=1, max_length=60)
    kind: Literal["fact", "check", "question", "impression"]
    scope: Literal["property", "unit"]
    label: str = Field(min_length=1, max_length=300)

    @field_validator("label", "section_key")
    @classmethod
    def clean(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("must not be blank")
        return trimmed


class VisitCustomItemResponse(BaseModel):
    id: UUID
    visit_id: UUID
    section_key: str
    kind: str
    scope: str
    label: str
    created_by: UUID
    created_at: datetime


# ---------------------------------------------------------------------------
# Entries (VC-3)
# ---------------------------------------------------------------------------

_MAX_ENTRIES_PER_BATCH = 200


class VisitEntryInput(BaseModel):
    """One answer.

    `visit_unit_id` is not the caller's choice: the item's own scope decides
    whether it carries one, and a mismatch is rejected rather than coerced
    (DESIGN §9.7) — a property answer filed against a unit is the failure the
    scope design exists to prevent.
    """

    item_key: str = Field(min_length=1, max_length=120)
    is_custom: bool = False
    visit_unit_id: UUID | None = None
    value: Any = None
    answer_text: str | None = Field(default=None, max_length=4000)
    note: str | None = Field(default=None, max_length=4000)
    # The row this author believed was current. VC-6 compares it against the
    # identity's real current row to surface an offline fork; stored either way.
    prev_entry_id: UUID | None = None

    @field_validator("answer_text", "note")
    @classmethod
    def blank_is_absent(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None


class VisitEntryBatch(BaseModel):
    """The sync-queue payload: one round trip carries a screenful of answers."""

    entries: list[VisitEntryInput] = Field(min_length=1, max_length=_MAX_ENTRIES_PER_BATCH)


class VisitEntryResponse(BaseModel):
    id: UUID
    visit_id: UUID
    item_key: str
    is_custom: bool
    visit_unit_id: UUID | None
    owner_user_id: UUID | None
    author_user_id: UUID
    value: Any = None
    answer_text: str | None
    note: str | None
    prev_entry_id: UUID | None
    created_at: datetime


# ---------------------------------------------------------------------------
# Defects (VC-4)
# ---------------------------------------------------------------------------


def _clean_title(value: str) -> str:
    trimmed = value.strip()
    if not 1 <= len(trimmed) <= 300:
        raise ValueError("title must be 1..300 non-blank characters")
    return trimmed


class VisitDefectCreate(BaseModel):
    """A problem found on the tour.

    `visit_unit_id` is null for the building rather than for "unknown" — a
    hallway defect belongs to the property, not to whichever unit happened to be
    selected when it was logged.
    """

    title: str = Field(min_length=1, max_length=300)
    visit_unit_id: UUID | None = None
    note: str | None = Field(default=None, max_length=4000)
    # Unrated by default: a number nobody chose is worse than no number.
    severity: int | None = Field(default=None, ge=1, le=5)
    promised_in_writing: bool = False
    resolution: str | None = Field(default=None, max_length=500)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return _clean_title(value)

    @field_validator("note", "resolution")
    @classmethod
    def blank_is_absent(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class VisitDefectPatch(BaseModel):
    title: str | None = None
    note: str | None = Field(default=None, max_length=4000)
    severity: int | None = Field(default=None, ge=1, le=5)
    promised_in_writing: bool | None = None
    resolution: str | None = Field(default=None, max_length=500)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str | None) -> str | None:
        return None if value is None else _clean_title(value)

    @model_validator(mode="after")
    def at_least_one_field(self) -> VisitDefectPatch:
        if not self.model_fields_set:
            raise ValueError("provide at least one field to change")
        return self


class VisitDefectResponse(BaseModel):
    id: UUID
    visit_id: UUID
    visit_unit_id: UUID | None
    from_item_key: str | None
    title: str
    note: str | None
    severity: int | None
    promised_in_writing: bool
    resolution: str | None
    created_by: UUID
    created_at: datetime
    deleted_at: datetime | None


# ---------------------------------------------------------------------------
# Fee Proposals (VC-7)
# ---------------------------------------------------------------------------

# The two accept paths, and what each may legally address. A tour can only
# offer figures the Listing already has somewhere to put: `fee_slot` names a
# §9.5 checklist slot, `override` a cost Criterion. Anything else is a typo
# that would create a row no surface renders, so it is refused (§9.7).
FEE_SLOT_TARGETS: frozenset[str] = frozenset(
    {
        "parking",
        "pet_rent",
        "pet_rent_cat",
        "pet_rent_dog",
        "insurance_program",
        "water_sewer",
        "valet_trash",
        "application_fee",
        "admin",
        "pet_deposit",
        "pet_fee",
    }
)

OVERRIDE_TARGETS: frozenset[str] = frozenset({"base_rent", "all_in_monthly"})


class VisitFeeProposalCreate(BaseModel):
    """A figure confirmed on the tour, offered to a Listing.

    It is an offer, not a write: nothing on the Listing changes until somebody
    with the cost-write permission accepts it (DESIGN §9.7).
    """

    hunt_listing_id: UUID
    visit_unit_id: UUID | None = None
    target: Literal["fee_slot", "override"]
    target_key: str = Field(min_length=1, max_length=120)
    amount: float = Field(ge=0)
    note: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def validate_target_key(self) -> VisitFeeProposalCreate:
        allowed = FEE_SLOT_TARGETS if self.target == "fee_slot" else OVERRIDE_TARGETS
        if self.target_key not in allowed:
            raise ValueError(f"{self.target_key!r} is not a valid {self.target} target")
        return self


class VisitFeeProposalDecision(BaseModel):
    """Accept performs the ordinary human write; reject records only the decision."""

    action: Literal["accept", "reject"]


class VisitFeeProposalResponse(BaseModel):
    id: UUID
    visit_id: UUID
    visit_unit_id: UUID | None
    hunt_listing_id: UUID
    target: Literal["fee_slot", "override"]
    target_key: str
    amount: float
    note: str | None
    status: Literal["pending", "accepted", "rejected"]
    decided_by: UUID | None
    decided_at: datetime | None
    created_by: UUID
    created_at: datetime
