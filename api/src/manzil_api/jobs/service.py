"""Jobs service — read jobs, guard state transitions, resume parked checkpoints."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from manzil_shared.models import CheckpointPrompt, JobState

from manzil_api.hunts.exceptions import InsufficientRole
from manzil_api.jobs.exceptions import (
    InvalidCheckpointAnswer,
    JobAlreadyDeleted,
    JobNotCancellable,
    JobNotDeletable,
    JobNotFound,
    JobNotRetryable,
    NotJobOwner,
)
from manzil_api.jobs.schemas import (
    AutoResolvedCheckpoint,
    CheckpointAnswer,
    CheckpointContext,
    CheckpointEvidence,
    JobDeletionReceipt,
    JobResponse,
    JobWarning,
)
from supabase import Client

# Every `jobs` column an API read may name, with `payload_public` standing in
# for `payload`. There is no `select("*")` on this table any more:
# `authenticated` holds SELECT on every column *except* `payload`
# (`20260901000010_jobs_payload_projection.sql`), which carries cleaned Source
# text, and PostgREST asks for all of them — so `*` is a hard `permission
# denied` rather than a silently missing key. Service-role reads name the same
# list so the two paths cannot drift.
JOB_COLUMNS = (
    "id,hunt_id,hunt_listing_id,type,state,current_stage,plan,payload_public,"
    "attempts,error,cost_actual_usd,created_at,started_at,finished_at,warnings,requested_by"
)


def _parse_payload(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        return json.loads(raw)
    return raw or {}


def job_payload(row: dict[str, Any]) -> dict[str, Any]:
    """The Job payload as a caller may see it, from either key.

    A table read names `payload_public`; the two checkpoint RPCs return the same
    projection under the key `payload`, because renaming it *there* would drop
    `checkpoint` and `auto_resolved_checkpoint` from the answered-checkpoint
    response silently — the Tasks UI would lose the prompt with no error
    anywhere. Normalising here means one accessor for both.

    Nothing this returns may ever be written back to `jobs.payload`: it is the
    redacted projection, and storing it would empty every Source body.
    """
    raw = row.get("payload_public")
    if raw is None:
        raw = row.get("payload")
    return _parse_payload(raw)


def _parse_warnings(raw: Any) -> list[JobWarning]:
    """`jobs.warnings` → the response list. Rows written before the column
    existed (and any shape the worker did not write) read as no warnings."""
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, list):
        return []
    return [JobWarning.model_validate(item) for item in raw if isinstance(item, dict)]


def _http_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value)
    return value if parsed.scheme in {"http", "https"} and parsed.netloc else None


def _checkpoint_context(run_state: dict[str, Any], prompt: CheckpointPrompt) -> CheckpointContext:
    source_url = _http_url(run_state.get("url"))
    evidence: list[CheckpointEvidence] = []
    claims: list[Any] = []
    if prompt.kind.value == "resolve_dispute":
        pending = run_state.get("pending_dispute")
        if isinstance(pending, dict):
            claims = pending.get("candidate_claims") or []
    else:
        claims = run_state.get("source_claims") or []

    for claim in claims:
        if not isinstance(claim, dict):
            continue
        if (
            prompt.kind.value == "confirm_value"
            and claim.get("criterion_key") != prompt.context_ref
        ):
            continue
        claim_url = _http_url(claim.get("source_id")) or source_url
        evidence.append(
            CheckpointEvidence(
                value=claim.get("value"),
                evidence_quote=claim.get("evidence_quote"),
                source_url=claim_url,
            )
        )
    return CheckpointContext(source_url=source_url, evidence=evidence)


def _auto_resolved_checkpoint(
    payload: dict[str, Any], *, state: str | None
) -> AutoResolvedCheckpoint | None:
    # Do not invite a correction while the default is still moving through the
    # pipeline; two concurrent projections could race. The provenance appears
    # as soon as the original Job reaches a terminal boundary.
    if state not in {JobState.DONE.value, JobState.FAILED.value}:
        return None
    raw = payload.get("auto_resolved_checkpoint")
    if not isinstance(raw, dict):
        return None
    prompt_raw = raw.get("prompt")
    snapshot = raw.get("snapshot")
    answer = raw.get("answer")
    resolved_at = raw.get("resolved_at")
    if (
        not isinstance(prompt_raw, dict)
        or not isinstance(snapshot, dict)
        or not isinstance(answer, dict)
        or not isinstance(resolved_at, str)
    ):
        return None
    prompt = CheckpointPrompt.model_validate(prompt_raw)
    return AutoResolvedCheckpoint(
        prompt=prompt,
        answer=answer,
        resolved_at=resolved_at,
        context=_checkpoint_context(snapshot, prompt),
        corrected_at=raw.get("corrected_at"),
        correction_job_id=raw.get("correction_job_id"),
    )


def row_to_response(row: dict[str, Any]) -> JobResponse:
    payload = job_payload(row)
    run_state = payload.get("run_state") or {}
    stage_index = run_state.get("cursor")
    if not isinstance(stage_index, int):
        stage_index = None
    checkpoint = None
    checkpoint_context = None
    if row.get("state") == JobState.WAITING_USER.value:
        cp = run_state.get("checkpoint")
        if cp is not None:
            checkpoint = CheckpointPrompt.model_validate(cp)
            checkpoint_context = _checkpoint_context(run_state, checkpoint)
    return JobResponse(
        id=row["id"],
        hunt_listing_id=row.get("hunt_listing_id"),
        type=row["type"],
        state=row["state"],
        current_stage=row.get("current_stage"),
        stage_index=stage_index,
        plan=row.get("plan"),
        attempts=row.get("attempts", 0),
        error=row.get("error"),
        cost_actual_usd=float(row.get("cost_actual_usd") or 0),
        created_at=row.get("created_at"),
        started_at=row.get("started_at"),
        finished_at=row.get("finished_at"),
        requested_by=row.get("requested_by"),
        checkpoint=checkpoint,
        checkpoint_context=checkpoint_context,
        auto_resolved_checkpoint=_auto_resolved_checkpoint(payload, state=row.get("state")),
        warnings=_parse_warnings(row.get("warnings")),
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
    response = client.table("jobs").select(JOB_COLUMNS).eq("id", str(job_id)).limit(1).execute()
    rows = response.data or []
    return rows[0] if rows else None


async def list_jobs(
    client: Client, hunt_id: UUID, states: list[JobState] | None
) -> list[JobResponse]:
    query = client.table("jobs").select(JOB_COLUMNS).eq("hunt_id", str(hunt_id))
    query = query.neq("state", JobState.DELETED.value)
    if states:
        query = query.in_("state", [s.value for s in states])
    query = (
        query.order("finished_at", desc=True, nullsfirst=False)
        .order("created_at", desc=True)
        .order("id", desc=True)
    )
    return [row_to_response(row) for row in query.execute().data or []]


async def delete_failed_job(client: Client, job_id: UUID) -> JobDeletionReceipt:
    try:
        response = client.rpc("delete_failed_job", {"p_job_id": str(job_id)}).execute()
    except Exception as exc:
        message = getattr(exc, "message", None) or str(exc)
        if "job_not_found" in message:
            raise JobNotFound(f"Job {job_id} not found") from exc
        if "job_already_deleted" in message:
            raise JobAlreadyDeleted("This Job was already deleted") from exc
        if "job_not_failed" in message:
            raise JobNotDeletable("Only failed Jobs may be deleted") from exc
        if "job_delete_permission_denied" in message:
            raise NotJobOwner("Only the requester or Hunt Owner may delete this Job") from exc
        if "hunt_locked" in message or "hunt_archived" in message:
            raise JobNotDeletable("Restore or unlock this Hunt before deleting its Jobs") from exc
        raise
    return JobDeletionReceipt.model_validate(response.data)


async def cancel_job(
    client: Client, job_id: UUID, user_id: str, *, authorized_admin: bool = False
) -> JobResponse:
    row = await get_job_row(client, job_id)
    if row is None:
        raise JobNotFound(f"Job {job_id} not found")
    if not authorized_admin:
        await _assert_manage_job(client, row, user_id)
    if row["state"] not in {
        JobState.QUEUED.value,
        JobState.RUNNING.value,
        JobState.WAITING_USER.value,
    }:
        raise JobNotCancellable(f"Job in state {row['state']} cannot be cancelled")
    # `returning="minimal"`: a representation would be `select *` on the
    # returned row, which now needs SELECT on `payload`. The fresh row comes
    # from `get_job_row` below in any case.
    client.table("jobs").update(
        {"state": JobState.CANCELLED.value, "finished_at": datetime.now(UTC).isoformat()},
        returning="minimal",
    ).eq("id", str(job_id)).execute()
    updated = await get_job_row(client, job_id)
    assert updated is not None
    return row_to_response(updated)


async def retry_job(
    client: Client, job_id: UUID, user_id: str, *, authorized_admin: bool = False
) -> JobResponse:
    row = await get_job_row(client, job_id)
    if row is None:
        raise JobNotFound(f"Job {job_id} not found")
    if not authorized_admin:
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
        },
        returning="minimal",
    ).eq("id", str(job_id)).execute()
    updated = await get_job_row(client, job_id)
    assert updated is not None
    return row_to_response(updated)


async def answer_checkpoint(
    client: Client, job_id: UUID, user_id: str, body: CheckpointAnswer
) -> JobResponse:
    row = await get_job_row(client, job_id)
    if row is None:
        raise JobNotFound(f"Job {job_id} not found")
    role, own = await _job_access(client, row, user_id)
    if role == "member" and not own:
        raise InsufficientRole("Members may resolve checkpoints only on their own Listings")

    payload = job_payload(row)
    auto_raw = payload.get("auto_resolved_checkpoint")
    if row["state"] != JobState.WAITING_USER.value:
        if not isinstance(auto_raw, dict):
            raise InvalidCheckpointAnswer("Job is not waiting for a checkpoint answer")
        prompt_raw = auto_raw.get("prompt")
        if not isinstance(prompt_raw, dict):
            raise InvalidCheckpointAnswer("Job has no auto-resolved checkpoint prompt")
        prompt = CheckpointPrompt.model_validate(prompt_raw)
        choice = body.answer.get("choice")
        if not isinstance(choice, str) or choice not in prompt.options:
            raise InvalidCheckpointAnswer(f"Answer must be one of {prompt.options}, got {choice!r}")
        response = client.rpc(
            "correct_auto_resolved_checkpoint",
            {"p_job_id": str(job_id), "p_answer": body.answer},
        ).execute()
        corrected = (response.data or [None])[0]
        if corrected is None:
            raise RuntimeError("checkpoint correction returned no Job")
        return row_to_response(corrected)

    run_state = payload.get("run_state") or {}
    cp_raw = run_state.get("checkpoint")
    if cp_raw is None:
        raise InvalidCheckpointAnswer("Job has no checkpoint prompt")
    prompt = CheckpointPrompt.model_validate(cp_raw)

    choice = body.answer.get("choice")
    if not isinstance(choice, str) or choice not in prompt.options:
        raise InvalidCheckpointAnswer(f"Answer must be one of {prompt.options}, got {choice!r}")

    # The RPC merges the answer into the Job's own stored payload; the API sends
    # the answer and nothing else. Sending back what it read here would be the
    # bug: `payload` above is the redacted projection, and storing it would
    # empty every Source body — silently, because a resumed EXTRACT *skips* an
    # emptied Source rather than failing. The rule the column list creates: no
    # user-JWT or projection-sourced read is ever written back to `payload`.
    #
    # The `choice` check above is a better error message, not a control: the RPC
    # is callable straight through PostgREST, so it validates the answer itself.
    response = client.rpc(
        "answer_job_checkpoint",
        {
            "p_job_id": str(job_id),
            "p_answer": body.answer,
            "p_detail": {
                "answer": body.answer,
                "kind": prompt.kind.value,
                "question": prompt.question,
            },
        },
    ).execute()
    updated = (response.data or [None])[0]
    if updated is None:
        raise RuntimeError("checkpoint answer returned no Job")
    return row_to_response(updated)
