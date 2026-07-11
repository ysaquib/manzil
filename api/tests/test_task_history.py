from __future__ import annotations

import json

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_legacy_job_history_reads_api_and_rls_events(
    collab_hunt, as_member: AsyncClient, db_pool, seeded_users
) -> None:
    plan = {"stages": ["fetch", "extract", "verify", "score"]}
    job_id = await db_pool.fetchval(
        """insert into jobs
           (hunt_id, hunt_listing_id, type, state, plan, cost_actual_usd, finished_at)
           values ($1, $2, 'ingest', 'done', $3::jsonb, 0.0123, now()) returning id""",
        collab_hunt["hunt_id"],
        collab_hunt["member_listing_id"],
        json.dumps(plan),
    )
    await db_pool.executemany(
        """insert into job_events (job_id, stage, event, detail)
           values ($1, $2, $3, $4::jsonb)""",
        [
            (job_id, "verify", "checkpoint_asked", json.dumps({"question": "Confirm?"})),
            (job_id, "verify", "checkpoint_answered", json.dumps({"answer": "yes"})),
            (job_id, "score", "completed", "{}"),
        ],
    )

    response = await as_member.get(
        f"/v1/hunts/{collab_hunt['hunt_id']}/jobs?state=done,failed,cancelled"
    )
    assert response.status_code == 200
    job = next(row for row in response.json() if row["id"] == str(job_id))
    assert job["plan"] == plan
    assert job["cost_actual_usd"] == 0.0123

    events = (
        seeded_users["member"]
        .supabase.table("job_events")
        .select("event,detail")
        .eq("job_id", str(job_id))
        .order("at")
        .execute()
        .data
    )
    assert [event["event"] for event in events] == [
        "checkpoint_asked",
        "checkpoint_answered",
        "completed",
    ]
