"""Jobs routes (Phase 1 plan §4.3). The `GET .../jobs` list is the one polled
read on the API surface (frontend polls it at 3s, P1-13)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from manzil_shared.models import JobState

from manzil_api.dependencies import CurrentUser, UserClient
from manzil_api.hunts.dependencies import OwnedHunt
from manzil_api.jobs import service
from manzil_api.jobs.schemas import CheckpointAnswer, JobResponse

router = APIRouter(tags=["jobs"])


@router.get("/hunts/{hunt_id}/jobs", response_model=list[JobResponse])
async def list_jobs(
    hunt_id: UUID,
    hunt: OwnedHunt,
    client: UserClient,
    state: Annotated[list[JobState] | None, Query()] = None,
) -> list[JobResponse]:
    return await service.list_jobs(client, hunt_id, state)


@router.post("/jobs/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(job_id: UUID, user: CurrentUser, client: UserClient) -> JobResponse:
    return await service.cancel_job(client, job_id, user.id)


@router.post("/jobs/{job_id}/retry", response_model=JobResponse)
async def retry_job(job_id: UUID, user: CurrentUser, client: UserClient) -> JobResponse:
    return await service.retry_job(client, job_id, user.id)


@router.post("/jobs/{job_id}/checkpoint", response_model=JobResponse)
async def answer_checkpoint(
    job_id: UUID, body: CheckpointAnswer, user: CurrentUser, client: UserClient
) -> JobResponse:
    return await service.answer_checkpoint(client, job_id, user.id, body)
