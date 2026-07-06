"""Pydantic domain models — DESIGN.md §3 terms, verbatim.

Field sets mirror the tables in DESIGN.md §8.2 and the enums in §8.1.
Pinned data-contract shapes represented here: catalog entry and rubric
option (§8.2), score breakdown (§9.3), checkpoint prompt (§10.10).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

# --- Enums (DESIGN §8.1) ---


class HuntRole(StrEnum):
    OWNER = "owner"
    CURATOR = "curator"
    MEMBER = "member"


class JobType(StrEnum):
    INGEST = "ingest"
    REFRESH = "refresh"
    RESCORE = "rescore"
    INVESTIGATE = "investigate"


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_USER = "waiting_user"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NOT_FOUND = "not_found"


class FetchOutcome(StrEnum):
    SUCCESS = "success"
    SHELL = "shell"
    BLOCKED = "blocked"
    NOT_LISTING = "not_listing"
    ERROR = "error"


class ValueState(StrEnum):
    EXTRACTED = "extracted"
    MANUAL = "manual"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


# --- Supporting enums used by the schema (§8.2) ---


class HuntDomain(StrEnum):
    RENT = "rent"
    BUY = "buy"


class CriterionDomain(StrEnum):
    RENT = "rent"
    BUY = "buy"
    BOTH = "both"


class CriterionCategory(StrEnum):
    UNIT = "unit"
    POLICY = "policy"
    COST = "cost"
    AVAILABILITY = "availability"
    CONDITION = "condition"
    LOCATION = "location"
    REPUTATION = "reputation"


class RequiresTool(StrEnum):
    MAPS = "maps"
    VISION = "vision"
    WEB_SEARCH = "web_search"


class RefreshClass(StrEnum):
    PRICING = "pricing"
    LISTING_DETAILS = "listing_details"
    IMAGES = "images"
    REVIEWS = "reviews"
    LOCATION = "location"


class ListingStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class MatchOp(StrEnum):
    EQ = "eq"
    LT = "lt"
    GT = "gt"
    RANGE = "range"
    IN = "in"
    BOOL = "bool"


class CheckpointKind(StrEnum):
    CONFIRM_VALUE = "confirm_value"
    RESOLVE_DEDUPE = "resolve_dedupe"
    RESOLVE_DISPUTE = "resolve_dispute"


class JobEventType(StrEnum):
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    CHECKPOINT_ASKED = "checkpoint_asked"
    CHECKPOINT_ANSWERED = "checkpoint_answered"
    CHECKPOINT_AUTO_RESOLVED = "checkpoint_auto_resolved"
    ESCALATED_TIER = "escalated_tier"


# --- Rubric option (pinned contract, §8.2) ---


class OptionMatch(BaseModel):
    op: MatchOp
    value: Any = None


class RubricOption(BaseModel):
    """Pinned shape (§8.2): {"match": {"op", "value"}, "delta", "dealbreaker_set_score"}."""

    match: OptionMatch
    delta: float
    dealbreaker_set_score: float | None = None


# --- Criterion / catalog entry (pinned contract, §8.2) ---


class CatalogEntry(BaseModel):
    """One `criteria_catalog` row. `value_schema` is the single source of truth
    for extraction schema generation, option validation, and widget rendering."""

    key: str
    label: str
    category: CriterionCategory
    domain: CriterionDomain
    value_schema: dict[str, Any]
    default_options: list[RubricOption]
    extraction_hint: str
    requires_tool: RequiresTool | None = None
    refresh_class: RefreshClass


class NonNegotiable(BaseModel):
    """Criterion-level gate: if no acceptable option matched, score is SET (§3 Gate)."""

    set_score: float


class RubricCriterion(BaseModel):
    hunt_id: UUID
    catalog_key: str | None = None
    custom_def: dict[str, Any] | None = None
    enabled: bool = True
    options: list[RubricOption] = Field(default_factory=list)
    unknown_delta: float = 0.0
    non_negotiable: NonNegotiable | None = None
    is_bonus: bool = False  # derived: all deltas >= 0 (§9.2)
    position: int = 0


# --- Global tables (§8.2) ---


class Property(BaseModel):
    id: UUID
    name: str
    canonical_address: str
    place_id: str | None = None
    lat: float | None = None
    lng: float | None = None
    official_url: str | None = None
    first_seen_at: datetime


class PropertySource(BaseModel):
    """§3 "Source": one known listing page (URL) for a Property on a specific site."""

    property_id: UUID
    url: str
    site_domain: str
    is_official: bool = False
    last_fetched_at: datetime | None = None
    last_success_at: datetime | None = None
    cleaned_text_path: str | None = None
    cleaned_text_hash: str | None = None
    image_urls: list[str] = Field(default_factory=list)
    screenshot_path: str | None = None


class FloorPlan(BaseModel):
    property_id: UUID
    source_id: UUID
    plan_name: str
    beds: int
    baths: float
    sqft_min: int | None = None
    sqft_max: int | None = None
    rent_min: Decimal | None = None
    rent_max: Decimal | None = None
    deposit: Decimal | None = None
    availability_date: date | None = None
    available_units: int | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class UnitGroup(BaseModel):
    """Derived grouping of a Property's floor plans by (beds, baths) — not a stored
    entity (§3). `key` is the pin key format used by `hunt_listings.pins` (§8.2)."""

    beds: int
    baths: float
    floor_plans: list[FloorPlan] = Field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.beds}-{self.baths}"


class Extraction(BaseModel):
    """Append-only agent-derived fact; current value = latest row per
    (property, hunt_id, criterion). `hunt_id` set only for custom criteria."""

    property_id: UUID
    hunt_id: UUID | None = None
    criterion_key: str
    value: Any = None
    confidence: Confidence
    evidence_quote: str | None = None
    source_id: UUID | None = None
    model: str
    resolution_rule: str | None = None
    extracted_at: datetime


class PropertyImage(BaseModel):
    property_id: UUID
    storage_path: str
    kind: str | None = None
    vision_assessment: dict[str, Any] | None = None


class UtilityBaseline(BaseModel):
    metro: str
    beds_bucket: int
    utility: str
    monthly_high: Decimal  # winter-weighted peak month (§9.5)
    monthly_median: Decimal
    sources: list[str] = Field(default_factory=list)
    refreshed_at: datetime


class AdapterRegistryEntry(BaseModel):
    """§3 "Adapter Registry": per-domain record of required fetch tier + settings."""

    site_domain: str
    required_tier: int
    adapter_config: dict[str, Any] = Field(default_factory=dict)
    last_success_tier: int | None = None
    last_outcome: FetchOutcome | None = None
    updated_at: datetime | None = None


# --- Per-hunt tables (§8.2) ---


class Hunt(BaseModel):
    id: UUID
    name: str
    owner_id: UUID
    domain: HuntDomain = HuntDomain.RENT
    rubric_version: int = 0
    settings: dict[str, Any] = Field(default_factory=dict)
    archived_at: datetime | None = None


class HuntMember(BaseModel):
    hunt_id: UUID
    user_id: UUID
    role: HuntRole
    color: str | None = None


class Invite(BaseModel):
    hunt_id: UUID
    email: str | None = None
    token: str
    role_granted: HuntRole = HuntRole.MEMBER
    created_by: UUID
    expires_at: datetime
    accepted_by: UUID | None = None


class HuntListing(BaseModel):
    """§3 "Listing": the association of a Property with a Hunt. `pins` maps a
    Unit Group key ("{beds}-{baths}") to a floor_plan_id (§9.4)."""

    hunt_id: UUID
    property_id: UUID
    added_by: UUID
    status: ListingStatus = ListingStatus.ACTIVE
    pins: dict[str, UUID] = Field(default_factory=dict)
    created_at: datetime | None = None


class Override(BaseModel):
    """Per-listing human-supplied value displayed over an extraction. Append-only."""

    hunt_listing_id: UUID
    criterion_key: str
    value: Any = None
    user_id: UUID
    note: str | None = None
    created_at: datetime | None = None


class FeeChecklistItem(BaseModel):
    hunt_listing_id: UUID
    fee_slot: str
    amount: Decimal | None = None
    value_state: ValueState = ValueState.UNKNOWN
    entered_by: UUID | None = None
    evidence_ref: str | None = None
    updated_at: datetime | None = None


class Comment(BaseModel):
    hunt_listing_id: UUID
    user_id: UUID
    body: str
    created_at: datetime | None = None
    deleted_at: datetime | None = None  # soft delete


class Rating(BaseModel):
    hunt_listing_id: UUID
    user_id: UUID
    rating: int


# --- Score breakdown (pinned contract, §9.3) ---


class GateFiring(BaseModel):
    key: str
    kind: Literal["dealbreaker", "non_negotiable"]
    set_score: float


class BreakdownCriterion(BaseModel):
    key: str
    value: Any = None
    matched: OptionMatch | None = None
    delta: float
    unknown: bool = False


class ScoreBreakdown(BaseModel):
    """When a gate fires: `total` = min set-score, `gates` populated, `criteria`
    empty — the delta pass never ran (§9.3)."""

    base: float = 10.0
    total: float
    rubric_version: int
    clamped: bool = False
    gates: list[GateFiring] = Field(default_factory=list)
    criteria: list[BreakdownCriterion] = Field(default_factory=list)


class Score(BaseModel):
    hunt_listing_id: UUID
    floor_plan_id: UUID
    total: float
    breakdown: ScoreBreakdown
    rubric_version: int
    computed_at: datetime | None = None


# --- Pipeline (§8.2, §10.10) ---


class CheckpointPrompt(BaseModel):
    """Pinned shape (§10.10): {kind, question, options, default, context_ref}."""

    kind: CheckpointKind
    question: str
    options: list[str] = Field(default_factory=lambda: ["yes", "no"])
    default: str
    context_ref: str | None = None


class Job(BaseModel):
    """Queue row, live task state, and permanent task history in one (§8.2)."""

    id: UUID
    hunt_listing_id: UUID | None = None
    type: JobType
    state: JobState = JobState.QUEUED
    current_stage: str | None = None
    plan: dict[str, Any] | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    attempts: int = 0
    error: str | None = None
    cost_actual_usd: Decimal = Decimal("0")
    locked_by: str | None = None
    locked_at: datetime | None = None
    created_at: datetime | None = None
    finished_at: datetime | None = None


class JobEvent(BaseModel):
    job_id: UUID
    stage: str
    event: JobEventType
    detail: dict[str, Any] = Field(default_factory=dict)
    at: datetime | None = None
