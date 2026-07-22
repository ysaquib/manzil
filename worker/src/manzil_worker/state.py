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

from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from manzil_shared.models import (
    CheckpointPrompt,
    Confidence,
    FetchOutcome,
    JobState,
    JobType,
    TargetScope,
    UnitApplicability,
)
from pydantic import BaseModel, Field

VerifyCheck = Literal["evidence", "conformance", "plausibility", "consistency"]

# Utilities a listing can state are included in rent (§9.5). Kept here so the
# EXTRACT schema block and the RunState model share one closed vocabulary.
UtilityKind = Literal["water", "sewer", "trash", "gas", "electric", "heat", "internet", "cable"]


class SourceClaim(BaseModel):
    """One sparse Source claim before/after Source-local target resolution."""

    criterion_key: str
    value: Any = None
    confidence: Confidence
    evidence_quote: str | None = None
    source_id: str | None = None  # Phase 0: the source URL; UUIDs arrive with the DB rows
    model: str
    prompt_version: int
    target_scope: TargetScope = TargetScope.PROPERTY
    floor_plan_ref: str | None = None
    floor_plan_id: UUID | None = None
    applicability: UnitApplicability | None = None
    claim_group_id: UUID = Field(default_factory=uuid4)
    origin_key: str | None = None
    resolution_rule: str | None = None
    disputed: bool = False
    candidate_claim_group_ids: list[UUID] = Field(default_factory=list)


class FloorPlanIn(BaseModel):
    """A floor plan as extracted from a page — plain JSON types; conversion to
    the shared FloorPlan model happens at the scoring/persistence boundary."""

    response_key: str | None = None
    source_native_id: str | None = None
    detail_url: str | None = None
    plan_name: str | None = None
    beds: int | None = None
    baths: float | None = None
    sqft_min: int | None = None
    sqft_max: int | None = None
    rent_min: float | None = None
    rent_max: float | None = None
    deposit: float | None = None
    availability_date: str | None = None  # ISO date; available_now rewritten in EXTRACT
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


class MandatoryFeeIn(BaseModel):
    """One mandatory recurring MONTHLY fee as stated on the page (§9.5, P3-9):
    water/sewer billing, valet trash, mandatory parking, insurance programs.
    One-time fees (admin, application, deposits) never belong here — all-in is
    a monthly figure."""

    name: str
    amount_monthly: float


class MandatoryFeesIn(BaseModel):
    """The page's mandatory recurring monthly fees (§9.5, P3-9) — a non-catalog
    EXTRACT block. Persisted both as a `mandatory_fees` extraction (rescore
    parity) and projected onto matching fee_checklist slots (state `extracted`;
    a human `manual` entry is never overwritten)."""

    fees: list[MandatoryFeeIn] = Field(default_factory=list)
    evidence_quote: str | None = None


class OneTimeFeeIn(BaseModel):
    """One one-time move-in cost as stated on the page (§9.5, §20 2026-07-18):
    application fee, admin fee, pet deposit/fee, other move-in charges.
    Never composes into all_in_monthly — all-in is a monthly figure; these are
    display metadata for the fees checklist's move-in section. `basis` states
    what one payment covers; `refundable` only when the page says so."""

    name: str
    amount: float
    basis: Literal["per_application", "per_person", "per_pet", "flat"] = "flat"
    refundable: bool | None = None


class OneTimeFeesIn(BaseModel):
    """The page's one-time move-in fees (§9.5) — a non-catalog EXTRACT block.
    Persisted as a `one_time_fees` extraction and projected onto the one-time
    fee_checklist slots (state `extracted`; `manual` never overwritten)."""

    fees: list[OneTimeFeeIn] = Field(default_factory=list)
    evidence_quote: str | None = None


class HeatingIn(BaseModel):
    """The unit's heating fuel as stated on the page (§9.5, P3-9): drives which
    winter-weighted baseline row the all-in composition applies. None when the
    page does not state it — composition then takes the worse of the two heat
    figures and flags it (heat_unknown)."""

    heating: Literal["gas", "electric"] | None = None
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
    image_urls: list[str] = Field(default_factory=list)
    authoritative_extraction: bool = False


class PropertyImageIn(BaseModel):
    """One normalized, content-addressed image prepared by IMAGE_FETCH (P3-7a)."""

    source_url: str
    storage_path: str
    content_hash: str
    width: int
    height: int
    byte_size: int
    kind: str | None = None
    vision_assessment: dict[str, Any] | None = None


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
    yielded no plans). `breakdown` is the pinned §9.3 contract dict.
    `all_in_components` is this plan's §9.5 composition detail (display
    metadata, projected onto scores.all_in_components) — optional-with-default
    so pre-P3-9 snapshots keep validating."""

    plan_name: str | None = None
    breakdown: dict[str, Any]
    all_in_components: dict[str, Any] | None = None


class SourceFreshness(BaseModel):
    """One persisted `property_sources` row's freshness inputs (P3-2), returned by
    PLAN's `fresh_source_lookup` seam. PLAN applies `PLAN_FRESH_TTL_HOURS` against
    `last_success_at`; the lookup itself is a dumb read so it fakes trivially in
    golden-manifest tests without a database."""

    cleaned_text_hash: str | None = None
    cleaned_text: str = ""
    last_success_at: datetime | None = None
    image_urls: list[str] = Field(default_factory=list)


class GeocodeIn(BaseModel):
    """A geocoded address (DEDUPE, P3-4): Google `place_id` + coordinates, as the
    Maps Geocoding API returns them. DEDUPE stores this on `RunState.geocode`; the
    terminal projection seeds `properties.place_id/lat/lng` from it (the §2.3
    forever-cache — a geocode is paid once per property, ever)."""

    place_id: str
    lat: float
    lng: float
    formatted_address: str | None = None
    city: str | None = None


class DedupeCandidate(BaseModel):
    """One existing `properties` row DEDUPE compares the incoming identity against
    (P3-4), returned by the `dedupe_candidates` seam. A dumb read of the identity
    columns — the match decision (distance + name similarity) lives in the stage,
    so it fakes trivially without a database (SourceFreshness pattern)."""

    id: UUID
    name: str | None = None
    canonical_address: str | None = None
    place_id: str | None = None
    lat: float | None = None
    lng: float | None = None


class DedupeDecision(BaseModel):
    """DEDUPE's recorded outcome (P3-4, DESIGN §10.3). `action` names the branch
    taken; the numbers behind a merge/keep-separate are retained for provenance
    and the Tasks timeline. Lives on RunState only — DEDUPE never writes the DB;
    the merge's DB effects happen in the queue projection."""

    action: Literal[
        "merged_auto",
        "merged_user",
        "kept_separate_user",
        "kept_separate",
        "no_identity",
        "no_address",
        "geocode_failed",
        "no_candidates",
    ]
    candidate_property_id: str | None = None
    distance_m: float | None = None
    name_similarity: float | None = None
    note: str | None = None


class DiscoveredSource(BaseModel):
    """One same-Property Source found by DISCOVER (P3-5).

    Domain, tier, and Syndication Family are deterministic worker metadata; the
    model supplies only the URL and same-Property judgment/evidence. `rank` is
    the planner's trust order used by baseline slate selection and P3-6's later
    escalation round. Official Sources are link-only and never slate members.
    """

    url: str
    site_domain: str
    required_tier: int
    syndication_family: str
    is_official: bool = False
    same_property_confidence: Confidence = Confidence.MEDIUM
    evidence: str | None = None
    rank: int = 0
    selected_for_slate: bool = False
    selection_reason: str | None = None


class PlanSource(BaseModel):
    """One source entry in the §10.4 manifest. Fetch entries carry `tier`; skip
    entries carry `why`. `url` identifies a brand-new submission whose
    `property_sources` row does not exist yet; `source_id` is used once the row
    does (both are optional so the honest identifier is recorded either way)."""

    source_id: str | None = None
    url: str | None = None
    action: Literal["fetch", "skip"]
    tier: int | None = None
    why: str | None = None


class PlanManifest(BaseModel):
    """The pinned §10.4 plan manifest — the runner's stage list travelling with
    the job (P3-2, §2.1). Do not reshape the keys. `stages` are the live stage
    names the runner walks; `skipped` maps a stage name to why it was dropped;
    `est_cost_usd` is the planned estimate compared against `cost_actual_usd`."""

    job_type: str
    trigger: str
    source_policy: str
    sources: list[PlanSource] = Field(default_factory=list)
    stages: list[str] = Field(default_factory=list)
    skipped: dict[str, str] = Field(default_factory=dict)
    est_cost_usd: float


class RunState(BaseModel):
    job_id: UUID
    job_type: JobType
    mode: Literal["workflow", "agents"] = "workflow"
    url: str
    source_policy: str = "tiers_1_2_3"  # §10.7; read by PLAN + DISCOVER (P3), inert in Phase 0
    hunt_listing_id: UUID | None = None  # None in Phase 0 CLI runs
    # §10.4 manifest (PLAN stage lands P3-2). Optional-with-default so pre-P3
    # RunState snapshots and recorded fixtures (plan absent/null) keep validating.
    plan: PlanManifest | None = None
    cursor: int = 0  # index into the stage list
    status: JobState = JobState.RUNNING
    error: str | None = None
    property_id: UUID | None = None
    # DEDUPE (P3-4): the geocode of this property's address and the merge/keep
    # decision. Optional-with-default so pre-P3 snapshots and recorded fixtures
    # (dedupe/geocode absent) keep validating.
    geocode: GeocodeIn | None = None
    dedupe: DedupeDecision | None = None
    # P3-5 DISCOVER outputs. Optional/defaulted so every pre-P3-5 snapshot keeps
    # validating. The candidate pool is retained even when policy excludes a
    # Source; P3-6 can draw from it without paying for a second search.
    discovered_sources: list[DiscoveredSource] = Field(default_factory=list)
    official_source_url: str | None = None
    slate_urls: list[str] = Field(default_factory=list)
    single_source_reason: Literal["trust_link", "discover_exhausted", "discover_failed"] | None = (
        None
    )
    discover_error: str | None = None
    sources: list[SourceState] = Field(default_factory=list)
    property_images: list[PropertyImageIn] = Field(default_factory=list)
    image_fetch_completed: bool = False
    source_claims: list[SourceClaim] = Field(default_factory=list)
    resolved_claims: list[SourceClaim] = Field(default_factory=list)
    floor_plans: list[FloorPlanIn] = Field(default_factory=list)
    property_identity: PropertyIdentityIn | None = None
    pet_costs: PetCostsIn | None = None
    utilities: UtilitiesIn | None = None
    # §9.5 P3-9 blocks. Optional-with-default like pet_costs/utilities so pre-P3-9
    # snapshots and recorded fixtures (blocks absent) keep validating.
    mandatory_fees: MandatoryFeesIn | None = None
    heating: HeatingIn | None = None
    one_time_fees: OneTimeFeesIn | None = None
    verify_flags: list[VerifyFlag] = Field(default_factory=list)
    effective_values: dict[str, Any] = Field(default_factory=dict)
    # §9.5 P3-9: the display plan's composition detail (components + tags +
    # badges), projected onto hunt_listings.all_in_components. Display metadata;
    # the pinned breakdown stays the scoring truth.
    all_in_components: dict[str, Any] | None = None
    scores: list[PlanScore] = Field(default_factory=list)
    display_score_index: int | None = None
    checkpoint: CheckpointPrompt | None = None
    checkpoint_answer: dict[str, Any] | None = None
    confirm_value_resolved: list[str] = Field(default_factory=list)
    cost_usd: float = 0.0
