"""Jobs routes (Phase 1 plan §4.3). The `GET .../jobs` list is the one polled
read on the API surface (frontend polls it at 3s, P1-13). Handlers stubbed."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from manzil_shared.models import JobState

from manzil_api.exceptions import NotImplementedYet
from manzil_api.hunts.dependencies import OwnedHunt
from manzil_api.jobs.schemas import CheckpointAnswer, JobResponse

router = APIRouter(tags=["jobs"])


@router.get("/hunts/{hunt_id}/jobs", response_model=list[JobResponse])
async def list_jobs(
    hunt_id: UUID,
    hunt: OwnedHunt,
    state: Annotated[list[JobState] | None, Query()] = None,
) -> list[JobResponse]:
    raise NotImplementedYet("list_jobs (P1-7/P1-13)")


@router.post("/jobs/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(job_id: UUID) -> JobResponse:
    raise NotImplementedYet("cancel_job — queued/running/waiting_user only (P1-7)")


@router.post("/jobs/{job_id}/retry", response_model=JobResponse)
async def retry_job(job_id: UUID) -> JobResponse:
    raise NotImplementedYet("retry_job — failed/cancelled only (P1-7)")


@router.post("/jobs/{job_id}/checkpoint", response_model=JobResponse)
async def answer_checkpoint(job_id: UUID, body: CheckpointAnswer) -> JobResponse:
    raise NotImplementedYet("answer_checkpoint — resume parked job (P1-7)")
