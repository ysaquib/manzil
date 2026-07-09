"""P1-7 jobs router tests."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from conftest import FAKE_USER
from httpx import AsyncClient
from manzil_shared.models import CheckpointKind, CheckpointPrompt, JobState


async def _seed_hunt_with_listing(db_pool):  # type: ignore[no-untyped-def]
    hunt_id, listing_id, property_id = uuid4(), uuid4(), uuid4()
    await db_pool.execute(
        "insert into hunts (id, name, owner_id) values ($1, 'J', $2)",
        hunt_id,
        FAKE_USER.id,
    )
    await db_pool.execute(
        "insert into properties (id, name, canonical_address) values ($1, 'P', 'a')",
        property_id,
    )
    await db_pool.execute(
        """
        insert into hunt_listings (id, hunt_id, property_id, added_by)
        values ($1, $2, $3, $4)
        """,
        listing_id,
        hunt_id,
        property_id,
        FAKE_USER.id,
    )
    return hunt_id, listing_id


@pytest.mark.asyncio
async def test_list_jobs_includes_rescore(client: AsyncClient, db_pool) -> None:
    hunt_id, _listing_id = await _seed_hunt_with_listing(db_pool)
    await db_pool.execute(
        """
        insert into jobs (hunt_id, type, state, payload)
        values ($1, 'rescore', 'queued', $2::jsonb)
        """,
        hunt_id,
        json.dumps({"hunt_id": str(hunt_id)}),
    )
    try:
        resp = await client.get(f"/v1/hunts/{hunt_id}/jobs?state=queued")
        assert resp.status_code == 200
        types = {j["type"] for j in resp.json()}
        assert "rescore" in types
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)


@pytest.mark.asyncio
async def test_cancel_guard_rejects_done(client: AsyncClient, db_pool) -> None:
    hunt_id, listing_id = await _seed_hunt_with_listing(db_pool)
    job_id = await db_pool.fetchval(
        """
        insert into jobs (hunt_id, hunt_listing_id, type, state, payload)
        values ($1, $2, 'ingest', 'done', '{}'::jsonb) returning id
        """,
        hunt_id,
        listing_id,
    )
    try:
        resp = await client.post(f"/v1/jobs/{job_id}/cancel")
        assert resp.status_code == 409
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)


@pytest.mark.asyncio
async def test_retry_resets_attempts(client: AsyncClient, db_pool) -> None:
    hunt_id, listing_id = await _seed_hunt_with_listing(db_pool)
    job_id = await db_pool.fetchval(
        """
        insert into jobs (hunt_id, hunt_listing_id, type, state, attempts, error, finished_at)
        values ($1, $2, 'ingest', 'failed', 3, 'boom', now()) returning id
        """,
        hunt_id,
        listing_id,
    )
    try:
        resp = await client.post(f"/v1/jobs/{job_id}/retry")
        assert resp.status_code == 200
        assert resp.json()["attempts"] == 0
        row = await db_pool.fetchrow(
            "select state, attempts, error, finished_at from jobs where id = $1", job_id
        )
        assert row["state"] == "queued"
        assert row["attempts"] == 0  # a human retry grants a fresh cycle budget
        assert row["error"] is None
        assert row["finished_at"] is None
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)


@pytest.mark.asyncio
async def test_parked_job_exposes_checkpoint(client: AsyncClient, db_pool) -> None:
    hunt_id, listing_id = await _seed_hunt_with_listing(db_pool)
    prompt = CheckpointPrompt(
        kind=CheckpointKind.CONFIRM_VALUE,
        question="Confirm beds=2?",
        options=["yes", "no"],
        default="yes",
    )
    payload = {
        "url": "https://example.com",
        "run_state": {
            "job_id": str(uuid4()),
            "job_type": "ingest",
            "url": "https://example.com",
            "status": JobState.WAITING_USER.value,
            "checkpoint": prompt.model_dump(mode="json"),
        },
    }
    job_id = await db_pool.fetchval(
        """
        insert into jobs (hunt_id, hunt_listing_id, type, state, payload)
        values ($1, $2, 'ingest', 'waiting_user', $3::jsonb) returning id
        """,
        hunt_id,
        listing_id,
        json.dumps(payload),
    )
    try:
        resp = await client.get(f"/v1/hunts/{hunt_id}/jobs?state=waiting_user")
        assert resp.status_code == 200
        job = next(j for j in resp.json() if j["id"] == str(job_id))
        assert job["checkpoint"]["question"] == "Confirm beds=2?"
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)


@pytest.mark.asyncio
async def test_answer_checkpoint_requeues(client: AsyncClient, db_pool) -> None:
    hunt_id, listing_id = await _seed_hunt_with_listing(db_pool)
    job_uuid = uuid4()
    prompt = CheckpointPrompt(
        kind=CheckpointKind.CONFIRM_VALUE,
        question="Confirm?",
        options=["yes", "no"],
        default="yes",
    )
    payload = {
        "url": "https://example.com",
        "run_state": {
            "job_id": str(job_uuid),
            "job_type": "ingest",
            "url": "https://example.com",
            "status": JobState.WAITING_USER.value,
            "checkpoint": prompt.model_dump(mode="json"),
        },
    }
    job_id = await db_pool.fetchval(
        """
        insert into jobs (id, hunt_id, hunt_listing_id, type, state, payload)
        values ($1, $2, $3, 'ingest', 'waiting_user', $4::jsonb) returning id
        """,
        job_uuid,
        hunt_id,
        listing_id,
        json.dumps(payload),
    )
    try:
        resp = await client.post(
            f"/v1/jobs/{job_id}/checkpoint",
            json={"answer": {"choice": "yes"}},
        )
        assert resp.status_code == 200
        row = await db_pool.fetchrow("select state, payload from jobs where id = $1", job_id)
        assert row["state"] == "queued"
        stored = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
        assert stored.get("checkpoint_answer") == {"choice": "yes", "context_ref": None}
        assert stored["run_state"]["checkpoint"] is None
        assert stored["run_state"]["status"] == JobState.RUNNING.value
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)
