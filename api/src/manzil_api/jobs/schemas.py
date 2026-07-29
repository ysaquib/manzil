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


class JobResponse(BaseModel):
    id: UUID
    hunt_listing_id: UUID | None
    type: JobType
    state: JobState
    current_stage: str | None
    plan: dict[str, Any] | None = None
    attempts: int
    error: str | None
    cost_actual_usd: float
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    checkpoint: CheckpointPrompt | None = None
    warnings: list[JobWarning] = Field(default_factory=list)


class CheckpointAnswer(BaseModel):
    """Answer to a parked `waiting_user` checkpoint (DESIGN §10.10)."""

    answer: dict[str, Any]
