"""P1-7 jobs router tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from api_helpers import FAKE_USER
from httpx import ASGITransport, AsyncClient
from manzil_api.main import create_app
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
async def test_list_jobs_comma_separated_states(client: AsyncClient, db_pool) -> None:
    hunt_id, listing_id = await _seed_hunt_with_listing(db_pool)
    await db_pool.execute(
        """
        insert into jobs (hunt_id, hunt_listing_id, type, state, payload)
        values ($1, $2, 'ingest', 'queued', '{}'::jsonb)
        """,
        hunt_id,
        listing_id,
    )
    await db_pool.execute(
        """
        insert into jobs (hunt_id, hunt_listing_id, type, state, payload)
        values ($1, $2, 'ingest', 'running', '{}'::jsonb)
        """,
        hunt_id,
        listing_id,
    )
    try:
        resp = await client.get(f"/v1/hunts/{hunt_id}/jobs?state=queued,running,waiting_user")
        assert resp.status_code == 200
        states = {j["state"] for j in resp.json()}
        assert "queued" in states
        assert "running" in states
        assert "done" not in states
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)


@pytest.mark.asyncio
async def test_site_admin_can_list_jobs_in_a_non_member_hunt(
    db_pool, collab_hunt, seeded_users
) -> None:
    """Ghost View is a SELECT widening, so the existing per-Hunt Tasks read
    must work without turning the Site Admin into a Hunt member."""
    outsider = seeded_users["outsider"]
    hunt_id = collab_hunt["hunt_id"]
    job_id = await db_pool.fetchval(
        "insert into jobs (hunt_id, type, state) "
        "values ($1, 'rescore', 'queued') returning id",
        hunt_id,
    )
    app = create_app()
    app.state.db_pool = db_pool

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {outsider.token}"},
        ) as ghost_client:
            # The same non-member is hidden before the account-level grant.
            hidden = await ghost_client.get(
                f"/v1/hunts/{hunt_id}/jobs?state=queued,running,waiting_user"
            )
            assert hidden.status_code == 404

            await db_pool.execute(
                "insert into site_admins (user_id) values ($1) on conflict do nothing",
                outsider.user_id,
            )
            try:
                visible = await ghost_client.get(
                    f"/v1/hunts/{hunt_id}/jobs?state=queued,running,waiting_user"
                )
                assert visible.status_code == 200
                assert str(job_id) in {job["id"] for job in visible.json()}
            finally:
                await db_pool.execute(
                    "delete from site_admins where user_id = $1", outsider.user_id
                )

        assert (
            await db_pool.fetchval(
                "select count(*) from hunt_members where hunt_id = $1 and user_id = $2",
                hunt_id,
                outsider.user_id,
            )
            == 0
        )
    finally:
        await db_pool.execute("delete from jobs where id = $1", job_id)


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
        context_ref="beds",
    )
    payload = {
        "url": "https://example.com",
        "run_state": {
            "job_id": str(uuid4()),
            "job_type": "ingest",
            "url": "https://example.com",
            "status": JobState.WAITING_USER.value,
            "checkpoint": prompt.model_dump(mode="json"),
            "source_claims": [
                {
                    "criterion_key": "beds",
                    "value": 2,
                    "evidence_quote": "Two-bedroom apartment",
                    "source_id": "https://example.com/listing",
                }
            ],
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
        assert job["checkpoint_context"]["evidence"] == [
            {
                "value": 2,
                "evidence_quote": "Two-bedroom apartment",
                "source_url": "https://example.com/listing",
            }
        ]
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


@pytest.mark.asyncio
async def test_late_answer_creates_correction_job_without_rewinding_history(
    client: AsyncClient, db_pool
) -> None:
    hunt_id, listing_id = await _seed_hunt_with_listing(db_pool)
    job_id = uuid4()
    prompt = CheckpointPrompt(
        kind=CheckpointKind.CONFIRM_VALUE,
        question="Accept the flagged rent?",
        options=["yes", "no"],
        default="yes",
        context_ref="base_rent",
    )
    snapshot = {
        "job_id": str(job_id),
        "job_type": "ingest",
        "url": "https://example.com/listing",
        "status": JobState.WAITING_USER.value,
        "cursor": 4,
        "checkpoint": prompt.model_dump(mode="json"),
        "source_claims": [
            {
                "criterion_key": "base_rent",
                "value": 2450,
                "evidence_quote": "$2,450 monthly rent",
                "source_id": "https://example.com/listing",
            }
        ],
    }
    payload = {
        "url": snapshot["url"],
        "run_state": {**snapshot, "status": "done", "checkpoint": None},
        "auto_resolved_checkpoint": {
            "prompt": prompt.model_dump(mode="json"),
            "answer": {"choice": "yes", "context_ref": "base_rent"},
            "resolved_at": datetime.now(UTC).isoformat(),
            "snapshot": snapshot,
        },
    }
    await db_pool.execute(
        """
        insert into jobs
            (id, hunt_id, hunt_listing_id, type, state, current_stage, payload, finished_at)
        values ($1, $2, $3, 'ingest', 'done', null, $4::jsonb, now())
        """,
        job_id,
        hunt_id,
        listing_id,
        json.dumps(payload),
    )
    await db_pool.execute(
        """
        insert into job_events (job_id, stage, event)
        values ($1, 'VERIFY', 'checkpoint_auto_resolved')
        """,
        job_id,
    )
    try:
        listed = await client.get(f"/v1/hunts/{hunt_id}/jobs?state=done")
        auto = next(job for job in listed.json() if job["id"] == str(job_id))
        assert auto["auto_resolved_checkpoint"]["answer"]["choice"] == "yes"
        assert auto["auto_resolved_checkpoint"]["context"]["evidence"][0] == {
            "value": 2450,
            "evidence_quote": "$2,450 monthly rent",
            "source_url": "https://example.com/listing",
        }

        response = await client.post(
            f"/v1/jobs/{job_id}/checkpoint",
            json={"answer": {"choice": "no"}},
        )
        assert response.status_code == 200
        correction = response.json()
        assert correction["id"] != str(job_id)
        assert correction["state"] == "queued"

        correction_row = await db_pool.fetchrow(
            "select payload from jobs where id = $1", UUID(correction["id"])
        )
        correction_payload = (
            json.loads(correction_row["payload"])
            if isinstance(correction_row["payload"], str)
            else correction_row["payload"]
        )
        assert correction_payload["corrects_job_id"] == str(job_id)
        assert correction_payload["checkpoint_answer"] == {
            "choice": "no",
            "context_ref": "base_rent",
        }
        assert correction_payload["run_state"]["job_id"] == correction["id"]
        assert correction_payload["run_state"]["cursor"] == 4
        assert correction_payload["run_state"]["checkpoint"] is None

        original = await db_pool.fetchval("select payload from jobs where id = $1", job_id)
        original_payload = json.loads(original) if isinstance(original, str) else original
        assert original_payload["auto_resolved_checkpoint"]["correction_job_id"] == correction["id"]
        assert original_payload["run_state"]["status"] == "done"
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)


@pytest.mark.asyncio
async def test_job_exposes_stage_warnings(client: AsyncClient, db_pool) -> None:
    """A degraded-but-successful run carries its warnings to the task card."""
    hunt_id, listing_id = await _seed_hunt_with_listing(db_pool)
    warnings = [
        {
            "stage": "IMAGE_CLASSIFY",
            "code": "classification_missing",
            "message": "The classifier skipped 2 of 30 photos.",
            "detail": {"content_hashes": ["a" * 64, "b" * 64]},
        }
    ]
    job_id = await db_pool.fetchval(
        """
        insert into jobs (hunt_id, hunt_listing_id, type, state, warnings)
        values ($1, $2, 'ingest', 'done', $3::jsonb) returning id
        """,
        hunt_id,
        listing_id,
        json.dumps(warnings),
    )
    try:
        resp = await client.get(f"/v1/hunts/{hunt_id}/jobs?state=done")
        assert resp.status_code == 200
        job = next(j for j in resp.json() if j["id"] == str(job_id))
        assert job["warnings"] == warnings
        assert job["error"] is None  # a warning is never a failure
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)


@pytest.mark.asyncio
async def test_job_without_warnings_reads_as_an_empty_list(client: AsyncClient, db_pool) -> None:
    hunt_id, listing_id = await _seed_hunt_with_listing(db_pool)
    job_id = await db_pool.fetchval(
        """
        insert into jobs (hunt_id, hunt_listing_id, type, state)
        values ($1, $2, 'ingest', 'done') returning id
        """,
        hunt_id,
        listing_id,
    )
    try:
        resp = await client.get(f"/v1/hunts/{hunt_id}/jobs?state=done")
        job = next(j for j in resp.json() if j["id"] == str(job_id))
        assert job["warnings"] == []
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)


@pytest.mark.asyncio
async def test_list_jobs_exposes_stage_index_from_run_state_cursor(
    client: AsyncClient, db_pool
) -> None:
    hunt_id, listing_id = await _seed_hunt_with_listing(db_pool)
    job_id = await db_pool.fetchval(
        """
        insert into jobs (hunt_id, hunt_listing_id, type, state, current_stage, payload)
        values ($1, $2, 'ingest', 'running', 'FETCH', $3::jsonb) returning id
        """,
        hunt_id,
        listing_id,
        json.dumps({"run_state": {"cursor": 7}}),
    )
    try:
        resp = await client.get(f"/v1/hunts/{hunt_id}/jobs?state=running")
        assert resp.status_code == 200
        job = next(j for j in resp.json() if j["id"] == str(job_id))
        assert job["stage_index"] == 7
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)
