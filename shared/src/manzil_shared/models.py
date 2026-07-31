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

from pydantic import BaseModel, Field, field_validator, model_validator

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
    """How Criteria are grouped for the person reading them (§8.2, §20 2026-07-25).

    Presentation vocabulary only: nothing in scoring, extraction, or persistence
    branches on it (fact scope, not category, decides Property vs Floor Plan
    handling). Categories are therefore grouped by the question a renter asks,
    and re-grouped freely as the Catalog grows.
    """

    UNIT = "unit"
    FITTINGS = "fittings"
    AMENITIES = "amenities"
    MANAGEMENT = "management"
    TENANCY = "tenancy"
    COST = "cost"
    LOCATION = "location"


class FactScope(StrEnum):
    PROPERTY = "property"
    FLOOR_PLAN = "floor_plan"
    MIXED = "mixed"
    COMPOSED = "composed"


class TargetScope(StrEnum):
    PROPERTY = "property"
    FLOOR_PLAN = "floor_plan"


class UnitApplicability(StrEnum):
    SPECIFIC_FLOOR_PLANS = "specific_floor_plans"
    ALL_UNITS = "all_units"
    SELECT_UNITS = "select_units"
    UNIT_SCOPE_UNSPECIFIED = "unit_scope_unspecified"


class ExtractionRecordKind(StrEnum):
    CANDIDATE = "candidate"
    RESOLVED = "resolved"


class EscalationPolicy(StrEnum):
    DECISION_RELEVANT = "decision_relevant"
    AVAILABLE_SOURCES_ONLY = "available_sources_only"


class ConflictPolicy(StrEnum):
    STANDARD_LADDER = "standard_ladder"
    VERIFIED_POSITIVE_PREFERRED = "verified_positive_preferred"


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
    LTE = "lte"
    GT = "gt"
    GTE = "gte"
    RANGE = "range"
    IN = "in"
    BOOL = "bool"
    CONTAINS_ANY = "contains_any"
    CONTAINS_ALL = "contains_all"


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
    fact_scope: FactScope = FactScope.PROPERTY
    value_schema: dict[str, Any]
    claim_value_schema: dict[str, Any] | None = None
    default_options: list[RubricOption]
    extraction_hint: str
    requires_tool: RequiresTool | None = None
    refresh_class: RefreshClass
    escalation_policy: EscalationPolicy = EscalationPolicy.DECISION_RELEVANT
    conflict_policy: ConflictPolicy = ConflictPolicy.STANDARD_LADDER


class CustomCriterionDef(BaseModel):
    """Versioned Hunt-scoped Criterion definition (DESIGN v3.35)."""

    schema_version: Literal[1] = 1
    key: str = Field(pattern=r"^custom:[0-9a-f]{8}-[0-9a-f-]{27}$")
    label: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=500)
    fact_scope: Literal["property", "floor_plan"]
    value_schema: dict[str, Any]
    requires_tool: RequiresTool | None = None
    refresh_class: RefreshClass
    routing_confirmed: bool

    @field_validator("label", "description")
    @classmethod
    def strip_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator("value_schema")
    @classmethod
    def supported_value_schema(cls, schema: dict[str, Any]) -> dict[str, Any]:
        schema_type = schema.get("type")
        if schema_type == "boolean" and set(schema) == {"type"}:
            return {"type": "boolean"}
        if schema_type == "number" and set(schema) == {"type"}:
            return {"type": "number"}
        if schema_type == "string" and set(schema) == {"type", "enum"}:
            values = schema.get("enum")
            normalized = (
                [item.strip() for item in values]
                if isinstance(values, list) and all(isinstance(item, str) for item in values)
                else []
            )
            if (
                isinstance(values, list)
                and 2 <= len(normalized) <= 20
                and all(normalized)
                and len(set(normalized)) == len(normalized)
            ):
                return {"type": "string", "enum": normalized}
        raise ValueError("custom value_schema must be boolean, number, or a 2-20 value string enum")

    @model_validator(mode="after")
    def route_contract(self) -> CustomCriterionDef:
        if not self.routing_confirmed:
            raise ValueError("custom Criterion routing must be human-confirmed")
        if self.requires_tool in (RequiresTool.VISION, RequiresTool.WEB_SEARCH):
            raise ValueError(f"custom route {self.requires_tool.value!r} is deferred")
        expected = (
            RefreshClass.LOCATION
            if self.requires_tool is RequiresTool.MAPS
            else RefreshClass.LISTING_DETAILS
        )
        if self.refresh_class is not expected:
            raise ValueError(f"refresh_class must be {expected.value!r} for this route")
        if self.requires_tool is RequiresTool.MAPS and self.fact_scope != "property":
            raise ValueError("Maps custom Criteria must be Property-scoped")
        return self


class NonNegotiable(BaseModel):
    """Criterion-level gate: if no acceptable option matched, score is SET (§3 Gate)."""

    set_score: float


class RubricCriterion(BaseModel):
    hunt_id: UUID
    catalog_key: str | None = None
    custom_def: CustomCriterionDef | None = None
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
    city: str | None = None
    state: str | None = None
    county: str | None = None
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
    id: UUID | None = None
    property_id: UUID
    source_id: UUID
    source_native_id: str | None = None
    detail_url: str | None = None
    plan_name: str
    beds: int
    baths: float
    unit_types: list[str] = Field(default_factory=list)
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
    """One row in the unified append-only scoped fact store (DESIGN §8.2)."""

    id: UUID | None = None
    property_id: UUID
    hunt_id: UUID | None = None
    criterion_key: str
    record_kind: ExtractionRecordKind
    origin_key: str
    target_scope: TargetScope
    floor_plan_id: UUID | None = None
    applicability: UnitApplicability | None = None
    claim_group_id: UUID
    value: Any = None
    confidence: Confidence
    evidence_quote: str | None = None
    source_id: UUID | None = None
    model: str
    resolution_rule: str | None = None
    disputed: bool = False
    job_id: UUID | None = None
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
    target_scope: TargetScope = TargetScope.PROPERTY
    floor_plan_id: UUID | None = None
    applicability: UnitApplicability | None = None
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

    def to_contract(self) -> dict[str, Any]:
        """Serialize to the exact pinned §9.3 JSON shape: `matched` is present even
        when null; `unknown` appears only when true. This is what `scores.breakdown`
        persists and what golden tests assert against."""
        criteria: list[dict[str, Any]] = []
        for c in self.criteria:
            entry: dict[str, Any] = {
                "key": c.key,
                "value": c.value,
                "matched": c.matched.model_dump(mode="json") if c.matched else None,
                "delta": c.delta,
            }
            if c.unknown:
                entry["unknown"] = True
            criteria.append(entry)
        return {
            "base": self.base,
            "total": self.total,
            "rubric_version": self.rubric_version,
            "clamped": self.clamped,
            "gates": [g.model_dump(mode="json") for g in self.gates],
            "criteria": criteria,
        }


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
