"""Jobs service — read jobs, guard state transitions, resume parked checkpoints."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from manzil_shared.models import CheckpointPrompt, JobState

from manzil_api.hunts.exceptions import InsufficientRole
from manzil_api.jobs.exceptions import (
    InvalidCheckpointAnswer,
    JobNotCancellable,
    JobNotFound,
    JobNotRetryable,
    NotJobOwner,
)
from manzil_api.jobs.schemas import CheckpointAnswer, JobResponse
from supabase import Client


def _parse_payload(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        return json.loads(raw)
    return raw or {}


def _row_to_response(row: dict[str, Any]) -> JobResponse:
    payload = _parse_payload(row.get("payload"))
    checkpoint = None
    if row.get("state") == JobState.WAITING_USER.value:
        run_state = payload.get("run_state") or {}
        cp = run_state.get("checkpoint")
        if cp is not None:
            checkpoint = CheckpointPrompt.model_validate(cp)
    return JobResponse(
        id=row["id"],
        hunt_listing_id=row.get("hunt_listing_id"),
        type=row["type"],
        state=row["state"],
        current_stage=row.get("current_stage"),
        plan=row.get("plan"),
        attempts=row.get("attempts", 0),
        error=row.get("error"),
        cost_actual_usd=float(row.get("cost_actual_usd") or 0),
        created_at=row.get("created_at"),
        finished_at=row.get("finished_at"),
        checkpoint=checkpoint,
    )


async def _job_access(client: Client, job: dict[str, Any], user_id: str) -> tuple[str, bool]:
    hunt_id = UUID(job["hunt_id"])
    role = (
        client.table("hunt_members")
        .select("role")
        .eq("hunt_id", str(hunt_id))
        .eq("user_id", user_id)
        .single()
        .execute()
        .data["role"]
    )
    own = False
    if job.get("hunt_listing_id"):
        rows = (
            client.table("hunt_listings")
            .select("added_by")
            .eq("id", job["hunt_listing_id"])
            .limit(1)
            .execute()
            .data
            or []
        )
        own = bool(rows and rows[0]["added_by"] == user_id)
    return role, own


async def _assert_manage_job(client: Client, job: dict[str, Any], user_id: str) -> None:
    role, own = await _job_access(client, job, user_id)
    if role != "owner" and not own:
        raise NotJobOwner("Only the submitter or Hunt Owner may manage this Job")


async def get_job_row(client: Client, job_id: UUID) -> dict[str, Any] | None:
    response = client.table("jobs").select("*").eq("id", str(job_id)).limit(1).execute()
    rows = response.data or []
    return rows[0] if rows else None


async def list_jobs(
    client: Client, hunt_id: UUID, states: list[JobState] | None
) -> list[JobResponse]:
    query = client.table("jobs").select("*").eq("hunt_id", str(hunt_id))
    if states:
        query = query.in_("state", [s.value for s in states])
    return [_row_to_response(row) for row in query.execute().data or []]


async def cancel_job(client: Client, job_id: UUID, user_id: str) -> JobResponse:
    row = await get_job_row(client, job_id)
    if row is None:
        raise JobNotFound(f"Job {job_id} not found")
    await _assert_manage_job(client, row, user_id)
    if row["state"] not in {
        JobState.QUEUED.value,
        JobState.RUNNING.value,
        JobState.WAITING_USER.value,
    }:
        raise JobNotCancellable(f"Job in state {row['state']} cannot be cancelled")
    client.table("jobs").update(
        {"state": JobState.CANCELLED.value, "finished_at": datetime.now(UTC).isoformat()}
    ).eq("id", str(job_id)).execute()
    updated = await get_job_row(client, job_id)
    assert updated is not None
    return _row_to_response(updated)


async def retry_job(client: Client, job_id: UUID, user_id: str) -> JobResponse:
    row = await get_job_row(client, job_id)
    if row is None:
        raise JobNotFound(f"Job {job_id} not found")
    await _assert_manage_job(client, row, user_id)
    if row["state"] not in {JobState.FAILED.value, JobState.CANCELLED.value}:
        raise JobNotRetryable(f"Job in state {row['state']} cannot be retried")
    client.table("jobs").update(
        {
            "state": JobState.QUEUED.value,
            "error": None,
            "attempts": 0,
            "locked_by": None,
            "locked_at": None,
            "finished_at": None,
        }
    ).eq("id", str(job_id)).execute()
    updated = await get_job_row(client, job_id)
    assert updated is not None
    return _row_to_response(updated)


async def answer_checkpoint(
    client: Client, job_id: UUID, user_id: str, body: CheckpointAnswer
) -> JobResponse:
    row = await get_job_row(client, job_id)
    if row is None:
        raise JobNotFound(f"Job {job_id} not found")
    role, own = await _job_access(client, row, user_id)
    if role == "member" and not own:
        raise InsufficientRole("Members may resolve checkpoints only on their own Listings")
    if row["state"] != JobState.WAITING_USER.value:
        raise InvalidCheckpointAnswer("Job is not waiting for a checkpoint answer")

    payload = _parse_payload(row.get("payload"))
    run_state = payload.get("run_state") or {}
    cp_raw = run_state.get("checkpoint")
    if cp_raw is None:
        raise InvalidCheckpointAnswer("Job has no checkpoint prompt")
    prompt = CheckpointPrompt.model_validate(cp_raw)

    choice = body.answer.get("choice")
    if not isinstance(choice, str) or choice not in prompt.options:
        raise InvalidCheckpointAnswer(f"Answer must be one of {prompt.options}, got {choice!r}")

    payload["checkpoint_answer"] = {
        **body.answer,
        "context_ref": prompt.context_ref,
    }
    run_state["status"] = JobState.RUNNING.value
    run_state["checkpoint"] = None
    payload["run_state"] = run_state

    response = client.rpc(
        "answer_job_checkpoint",
        {
            "p_job_id": str(job_id),
            "p_payload": payload,
            "p_detail": {"answer": body.answer},
        },
    ).execute()
    updated = (response.data or [None])[0]
    if updated is None:
        raise RuntimeError("checkpoint answer returned no Job")
    return _row_to_response(updated)
