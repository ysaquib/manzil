"""Jobs request/response shapes (DESIGN §8.2 `jobs`)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from manzil_shared.models import CheckpointPrompt, JobState, JobType
from pydantic import BaseModel, Field


class JobWarning(BaseModel):
    """A non-fatal degradation the run wants shown on the task card (§10.8).

    The run continued; nothing is parked and nothing failed. Mirrors the
    worker's `StageWarning`.
    """

    stage: str
    code: str
    message: str
    detail: dict[str, Any] = Field(default_factory=dict)


class CheckpointEvidence(BaseModel):
    """One compact piece of Source context for a checkpoint decision."""

    value: Any = None
    evidence_quote: str | None = None
    source_url: str | None = None


class CheckpointContext(BaseModel):
    """Evidence and Source links shown instead of a stored page screenshot."""

    source_url: str | None = None
    evidence: list[CheckpointEvidence] = Field(default_factory=list)


class AutoResolvedCheckpoint(BaseModel):
    """Visible provenance for a default applied by the scheduler."""

    prompt: CheckpointPrompt
    answer: dict[str, Any]
    resolved_at: datetime
    context: CheckpointContext
    corrected_at: datetime | None = None
    correction_job_id: UUID | None = None


class JobResponse(BaseModel):
    id: UUID
    hunt_listing_id: UUID | None
    type: JobType
    state: JobState
    current_stage: str | None
    # Index into plan.stages (RunState.cursor). None when no persisted run_state.
    stage_index: int | None = None
    plan: dict[str, Any] | None = None
    attempts: int
    error: str | None
    cost_actual_usd: float
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    requested_by: UUID | None = None
    checkpoint: CheckpointPrompt | None = None
    checkpoint_context: CheckpointContext | None = None
    auto_resolved_checkpoint: AutoResolvedCheckpoint | None = None
    warnings: list[JobWarning] = Field(default_factory=list)


class JobDeletionReceipt(BaseModel):
    job_id: UUID
    deleted_at: datetime
    deleted_from_state: JobState
    removed_placeholder_listing: bool
    retained_cost_usd: float


class CheckpointAnswer(BaseModel):
    """Answer to a parked `waiting_user` checkpoint (DESIGN §10.10)."""

    answer: dict[str, Any]
