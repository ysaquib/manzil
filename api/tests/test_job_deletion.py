"""Soft-deleted Jobs disappear while their operational history remains."""

from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def _failed_job(db_pool, collab_hunt, requester, *, listing: str | None = None):
    job_id = await db_pool.fetchval(
        """insert into jobs (
               hunt_id, hunt_listing_id, type, state, requested_by, cost_actual_usd, error
           ) values ($1,$2,'refresh','failed',$3,0.0123,'test failure') returning id""",
        UUID(collab_hunt["hunt_id"]),
        UUID(listing or collab_hunt["member_listing_id"]),
        requester,
    )
    await db_pool.execute(
        "insert into job_events(job_id,stage,event,detail) values($1,'FETCH','failed','{}')",
        job_id,
    )
    return job_id


async def test_requester_can_delete_failed_job_and_history_and_cost_remain(
    as_member: AsyncClient, db_pool, collab_hunt, seeded_users
) -> None:
    job_id = await _failed_job(db_pool, collab_hunt, seeded_users["member"].user_id)

    response = await as_member.delete(f"/v1/jobs/{job_id}")

    assert response.status_code == 200
    assert response.json()["retained_cost_usd"] == 0.0123
    row = await db_pool.fetchrow(
        "select state::text, deleted_from_state::text, cost_actual_usd from jobs where id=$1",
        job_id,
    )
    assert row["state"] == "deleted"
    assert row["deleted_from_state"] == "failed"
    assert float(row["cost_actual_usd"]) == 0.0123
    assert await db_pool.fetchval("select count(*) from job_events where job_id=$1", job_id) == 1
    listed = await as_member.get(f"/v1/hunts/{collab_hunt['hunt_id']}/jobs")
    assert str(job_id) not in {job["id"] for job in listed.json()}


async def test_non_requester_cannot_delete_another_members_failed_job(
    as_curator: AsyncClient, db_pool, collab_hunt, seeded_users
) -> None:
    job_id = await _failed_job(db_pool, collab_hunt, seeded_users["member"].user_id)
    try:
        response = await as_curator.delete(f"/v1/jobs/{job_id}")
        assert response.status_code == 403
        state = await db_pool.fetchval("select state::text from jobs where id=$1", job_id)
        assert state == "failed"
    finally:
        await db_pool.execute("delete from jobs where id=$1", job_id)


async def test_only_failed_jobs_are_member_deletable(
    as_owner: AsyncClient, db_pool, collab_hunt, seeded_users
) -> None:
    job_id = await db_pool.fetchval(
        """insert into jobs(hunt_id,type,state,requested_by)
           values($1,'rescore','done',$2) returning id""",
        UUID(collab_hunt["hunt_id"]),
        seeded_users["owner"].user_id,
    )
    try:
        response = await as_owner.delete(f"/v1/jobs/{job_id}")
        assert response.status_code == 409
    finally:
        await db_pool.execute("delete from jobs where id=$1", job_id)
