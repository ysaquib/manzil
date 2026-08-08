"""Admin panel response shapes (AD-1)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class AdminIdentity(BaseModel):
    """What the frontend needs to decide whether to render the Admin nav item.

    `is_primordial` is exposed because the panel must not offer a *Revoke*
    control the database will refuse — a button that always errors is worse
    than no button.
    """

    user_id: UUID
    is_site_admin: bool
    is_primordial: bool
    granted_at: datetime | None = None


class AdminSummary(BaseModel):
    """The Overview tab's counters."""

    users: int
    hunts: int
    listings: int
    jobs_failed: int
    jobs_total: int
    spend_usd_30d: float
    tier3_credits_used: int
    tier3_credits_allowance: int | None = None
    feedback_new: int


class HuntSummary(BaseModel):
    hunt_id: UUID
    name: str
    owner_id: UUID | None = None
    owner_name: str | None = None
    members: int
    listings: int
    jobs: int
    llm_cost_usd: float
    fetch_cost_usd: float
    total_cost_usd: float
    created_at: datetime
    last_activity_at: datetime | None = None


class AuditEntry(BaseModel):
    id: UUID
    admin_user_id: UUID
    action: str
    target_type: str | None = None
    target_id: UUID | None = None
    target_label: str | None = None
    hunt_id: UUID | None = None
    via_ghost_view: bool
    occurred_at: datetime


class ActivityEntry(BaseModel):
    """One row of the derived Hunt activity feed (AD-F)."""

    hunt_id: UUID
    occurred_at: datetime
    actor_id: UUID | None = None
    kind: str
    subject_type: str
    subject_id: UUID | None = None
    subject_label: str | None = None
    detail: dict = Field(default_factory=dict)


class GrantAdmin(BaseModel):
    user_id: UUID
    note: str | None = Field(default=None, max_length=500)


FEEDBACK_TRIAGE = ("new", "seen", "actioned", "wont_fix")


class FeedbackReport(BaseModel):
    """One row of the inbox. `route` and `user_agent` are what turn a two-line
    report into something reproducible, so they are first-class here rather than
    buried in a detail view."""

    id: UUID
    category: str
    body: str
    route: str | None = None
    hunt_id: UUID | None = None
    hunt_name: str | None = None
    app_version: str | None = None
    user_agent: str | None = None
    reporter_id: UUID
    reporter_name: str | None = None
    reporter_email: str | None = None
    triage: str
    triaged_at: datetime | None = None
    created_at: datetime


class FeedbackTriageUpdate(BaseModel):
    triage: Literal["new", "seen", "actioned", "wont_fix"]


class FeedbackCounts(BaseModel):
    """Drives the filter chips, so an empty state is distinguishable from a
    filtered-out one."""

    new: int = 0
    seen: int = 0
    actioned: int = 0
    wont_fix: int = 0


# ── People (AD-3) ────────────────────────────────────────────────────────────


class PersonMembership(BaseModel):
    hunt_id: UUID
    hunt_name: str
    role: str
    joined_at: datetime | None = None


class PersonRow(BaseModel):
    """Roster row. `suspended` is derived from the auth ban, not stored twice."""

    user_id: UUID
    email: str | None = None
    display_name: str | None = None
    confirmed: bool
    suspended: bool
    hunts: int
    owns: int
    created_at: datetime
    last_sign_in_at: datetime | None = None
    spend_usd: float = 0.0
    is_site_admin: bool = False


class PersonDetail(PersonRow):
    memberships: list[PersonMembership] = Field(default_factory=list)
    feedback_count: int = 0
    # Set when deletion would be refused, so the UI can offer the fix inline
    # rather than surfacing an error after the click.
    blocking_owned_hunts: list[PersonMembership] = Field(default_factory=list)


class ProvisionPerson(BaseModel):
    # Plain str, as in invites/schemas.py — Supabase Auth is the real validator,
    # and email-validator is not a dependency this repo carries.
    email: str = Field(min_length=3, max_length=320)
    # Optional straight-into-a-Hunt invite. Both or neither.
    hunt_id: UUID | None = None
    role: Literal["owner", "curator", "member"] | None = None


class UpdatePerson(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    email: str | None = Field(default=None, min_length=3, max_length=320)
    confirm_email: bool | None = None


class SetMembership(BaseModel):
    hunt_id: UUID
    role: Literal["owner", "curator", "member"]


class ActionResult(BaseModel):
    status: str = "ok"
    detail: str | None = None


# ── Jobs / Costs / System (AD-5) ─────────────────────────────────────────────


class JobRow(BaseModel):
    id: UUID
    hunt_id: UUID | None = None
    hunt_name: str | None = None
    listing_name: str | None = None
    type: str
    state: str
    current_stage: str | None = None
    attempts: int
    error: str | None = None
    cost_actual_usd: float
    created_at: datetime
    finished_at: datetime | None = None
    locked_by: str | None = None
    locked_at: datetime | None = None
    # A `running` Job whose heartbeat has gone stale: its worker is gone and the
    # lock will never be released on its own.
    stale: bool = False


class JobDetail(JobRow):
    events: list[dict] = Field(default_factory=list)
    stage_costs: list[dict] = Field(default_factory=list)


class SpendBucket(BaseModel):
    label: str
    llm_cost_usd: float
    fetch_cost_usd: float
    total_cost_usd: float
    llm_calls: int = 0
    fetch_calls: int = 0


class SpendPoint(BaseModel):
    day: date
    llm_cost_usd: float
    fetch_cost_usd: float


class CostsReport(BaseModel):
    days: int
    by_stage: list[SpendBucket] = Field(default_factory=list)
    by_hunt: list[SpendBucket] = Field(default_factory=list)
    by_model: list[SpendBucket] = Field(default_factory=list)
    # `by_model` folds stage spend under each stage's *current* pin. True is the
    # honest answer and the UI says so: a re-pinned stage files its old spend
    # under the new model.
    grouped_by_current_pin: bool = True
    daily: list[SpendPoint] = Field(default_factory=list)
    tier3_credits_used: int = 0
    tier3_credits_allowance: int | None = None


class SystemReport(BaseModel):
    queued: int
    running: int
    stale_locks: int
    oldest_queued_seconds: float
    last_heartbeat: datetime | None = None
    finished_24h: int
    failed_24h: int
    last_migration: str | None = None
    model_pins: list[dict] = Field(default_factory=list)
    services: list[dict] = Field(default_factory=list)
    priced_models: int
    mode: str
