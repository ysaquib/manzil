"""Jobs routes (Phase 1 plan §4.3). The `GET .../jobs` list is the one polled
read on the API surface (frontend polls it at 3s, P1-13)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from manzil_shared.models import JobState

from manzil_api.dependencies import CurrentUser, UserClient
from manzil_api.hunts.dependencies import ValidHunt
from manzil_api.jobs import service
from manzil_api.jobs.dependencies import parse_job_states
from manzil_api.jobs.schemas import CheckpointAnswer, JobResponse

router = APIRouter(tags=["jobs"])


@router.get("/hunts/{hunt_id}/jobs", response_model=list[JobResponse])
async def list_jobs(
    hunt_id: UUID,
    hunt: ValidHunt,
    client: UserClient,
    state: Annotated[list[JobState] | None, Depends(parse_job_states)],
) -> list[JobResponse]:
    # `valid_hunt_id` is backed by the caller's RLS-scoped client. Members can
    # see their Hunts; Site Admins can additionally see a non-member Hunt via
    # the SELECT-only Ghost View predicate. Requiring a membership row here
    # incorrectly turned that valid admin read into a 404. Mutations keep their
    # separate manage/checkpoint permission paths below.
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
