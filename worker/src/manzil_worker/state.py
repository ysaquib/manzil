"""RunState — the one Pydantic object every stage maps over (IMPLEMENTATION §3,
DESIGN §10.2). Stages are `(RunState, StageCtx) -> RunState`; the runner
persists state BEFORE advancing the cursor, which is what makes runs
resumable, deploy-safe, and checkpoint-cheap (NFR3).

IMPLEMENTATION §3 marks these interfaces as proposals the code is supposed to
settle; deviations from the sketch are deliberate and noted in the §9
changelog (cost as float to match the seam's tally; `status`/`error`/`scores`
fields added because the CLI and eval harness need run outcomes on the state).
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from manzil_shared.models import (
    CheckpointPrompt,
    Confidence,
    FetchOutcome,
    JobState,
    JobType,
)
from pydantic import BaseModel, Field

VerifyCheck = Literal["evidence", "conformance", "plausibility", "consistency"]

# Utilities a listing can state are included in rent (§9.5). Kept here so the
# EXTRACT schema block and the RunState model share one closed vocabulary.
UtilityKind = Literal[
    "water", "sewer", "trash", "gas", "electric", "heat", "internet", "cable"
]


class FieldExtraction(BaseModel):
    """One extracted fact with its provenance (IMPL §3)."""

    value: Any = None
    confidence: Confidence
    evidence_quote: str | None = None
    source_id: str | None = None  # Phase 0: the source URL; UUIDs arrive with the DB rows
    model: str
    prompt_version: int


class FloorPlanIn(BaseModel):
    """A floor plan as extracted from a page — plain JSON types; conversion to
    the shared FloorPlan model happens at the scoring/persistence boundary."""

    plan_name: str | None = None
    beds: int | None = None
    baths: float | None = None
    sqft_min: int | None = None
    sqft_max: int | None = None
    rent_min: float | None = None
    rent_max: float | None = None
    deposit: float | None = None
    availability_date: str | None = None  # ISO date
    evidence_quote: str | None = None


class PropertyIdentityIn(BaseModel):
    """The property's own identity as stated on the page — plain JSON types,
    unscored display metadata (DESIGN §20 2026-07-10): projected onto the
    global `properties` row, never into the rubric/scoring path."""

    name: str | None = None
    address: str | None = None
    official_url: str | None = None


class PetCostsIn(BaseModel):
    """Per-pet monthly rent as stated on the page — plain JSON types, a
    non-catalog EXTRACT block (§9.5 v1). Projected onto the fee_checklist pet
    slots at persistence, never into the rubric/scoring criteria path. Species-
    specific fields are populated only when the page distinguishes cat vs dog;
    the generic field only when it states one per-pet figure without species."""

    cat_rent_monthly: float | None = None
    dog_rent_monthly: float | None = None
    pet_rent_monthly: float | None = None  # species-unspecified
    evidence_quote: str | None = None


class UtilitiesIn(BaseModel):
    """Utilities the listing states are INCLUDED in rent (§9.5) — a non-catalog
    EXTRACT block stored as a `utilities_included` extraction, unscored display
    metadata. `included` is an empty list when the page says none are included
    and None when the page says nothing about utilities."""

    included: list[UtilityKind] | None = None
    evidence_quote: str | None = None


class SourceState(BaseModel):
    """One source's fetch results (IMPL §3: url, tier_used, outcome, cleaned, hash)."""

    url: str
    is_official: bool = False
    tier_used: int | None = None
    outcome: FetchOutcome | None = None
    cleaned_text: str = ""
    cleaned_hash: str = ""
    fee_tables_found: int = 0


class VerifyFlag(BaseModel):
    """A VERIFY demotion record: which check fired on which criterion and why.
    Phase 0 records flags; checkpoint escalation for gate-bearing criteria
    activates in Phase 1 when jobs/waiting_user exist."""

    criterion_key: str
    check: VerifyCheck
    note: str
    source_id: str | None = None


class PlanScore(BaseModel):
    """One scored floor plan (or the plan-less property score when the page
    yielded no plans). `breakdown` is the pinned §9.3 contract dict."""

    plan_name: str | None = None
    breakdown: dict[str, Any]


class RunState(BaseModel):
    job_id: UUID
    job_type: JobType
    mode: Literal["workflow", "agents"] = "workflow"
    url: str
    source_policy: str = "tiers_1_2_3"  # §10.7; read by PLAN + DISCOVER (P3), inert in Phase 0
    hunt_listing_id: UUID | None = None  # None in Phase 0 CLI runs
    plan: dict[str, Any] | None = None  # §10.4 manifest shape (PLAN stage lands P3-2)
    cursor: int = 0  # index into the stage list
    status: JobState = JobState.RUNNING
    error: str | None = None
    property_id: UUID | None = None
    sources: list[SourceState] = Field(default_factory=list)
    extractions: dict[str, list[FieldExtraction]] = Field(default_factory=dict)
    reconciled: dict[str, FieldExtraction] = Field(default_factory=dict)
    floor_plans: list[FloorPlanIn] = Field(default_factory=list)
    property_identity: PropertyIdentityIn | None = None
    pet_costs: PetCostsIn | None = None
    utilities: UtilitiesIn | None = None
    verify_flags: list[VerifyFlag] = Field(default_factory=list)
    effective_values: dict[str, Any] = Field(default_factory=dict)
    scores: list[PlanScore] = Field(default_factory=list)
    display_score_index: int | None = None
    checkpoint: CheckpointPrompt | None = None
    checkpoint_answer: dict[str, Any] | None = None
    confirm_value_resolved: list[str] = Field(default_factory=list)
    cost_usd: float = 0.0
