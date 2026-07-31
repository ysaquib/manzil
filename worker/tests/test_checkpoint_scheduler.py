"""P3-11 checkpoint timeout sweep."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import asyncpg
import pytest
from manzil_worker.queue import checkpoint_timeout_tick


@pytest.mark.parametrize(
    ("kind", "default", "options"),
    [
        ("confirm_value", "yes", ["yes", "no"]),
        ("resolve_dedupe", "keep_separate", ["merge", "keep_separate"]),
        ("resolve_dispute", "Leave unknown", ["Use source A", "Leave unknown"]),
    ],
)
async def test_timeout_applies_declared_default_and_preserves_correction_snapshot(
    pg_pool: asyncpg.Pool,
    kind: str,
    default: str,
    options: list[str],
) -> None:
    hunt_id, property_id, listing_id, owner_id = uuid4(), uuid4(), uuid4(), uuid4()
    job_id = uuid4()
    prompt = {
        "kind": kind,
        "question": f"Resolve {kind}?",
        "options": options,
        "default": default,
        "context_ref": "criterion:test",
    }
    run_state = {
        "job_id": str(job_id),
        "job_type": "ingest",
        "url": "https://example.com/listing",
        "status": "waiting_user",
        "cursor": 4,
        "checkpoint": prompt,
    }
    await pg_pool.execute(
        "insert into hunts (id, name, owner_id) values ($1, 'Checkpoint Hunt', $2)",
        hunt_id,
        owner_id,
    )
    await pg_pool.execute(
        """
        insert into properties (id, name, canonical_address)
        values ($1, 'Checkpoint Place', '1 Clock St')
        """,
        property_id,
    )
    await pg_pool.execute(
        """
        insert into hunt_listings (id, hunt_id, property_id, added_by)
        values ($1, $2, $3, $4)
        """,
        listing_id,
        hunt_id,
        property_id,
        owner_id,
    )
    await pg_pool.execute(
        """
        insert into jobs
            (id, hunt_id, hunt_listing_id, type, state, current_stage, payload)
        values ($1, $2, $3, 'ingest', 'waiting_user', 'VERIFY', $4::jsonb)
        """,
        job_id,
        hunt_id,
        listing_id,
        json.dumps({"url": run_state["url"], "run_state": run_state}),
    )
    await pg_pool.execute(
        """
        insert into job_events (job_id, stage, event, at)
        values ($1, 'VERIFY', 'checkpoint_asked', $2)
        """,
        job_id,
        datetime.now(UTC) - timedelta(hours=25),
    )
    try:
        await checkpoint_timeout_tick(pg_pool)

        row = await pg_pool.fetchrow("select state, payload from jobs where id = $1", job_id)
        assert row is not None
        payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
        assert row["state"] == "queued"
        assert payload["checkpoint_answer"] == {
            "choice": default,
            "context_ref": "criterion:test",
        }
        assert payload["run_state"]["checkpoint"] is None
        assert payload["run_state"]["status"] == "running"
        meta = payload["auto_resolved_checkpoint"]
        assert meta["prompt"] == prompt
        assert meta["snapshot"]["checkpoint"] == prompt
        assert meta["snapshot"]["status"] == "waiting_user"

        event = await pg_pool.fetchrow(
            """
            select event, detail from job_events
            where job_id = $1 and event = 'checkpoint_auto_resolved'
            """,
            job_id,
        )
        assert event is not None
        detail = (
            json.loads(event["detail"]) if isinstance(event["detail"], str) else event["detail"]
        )
        assert detail["answer"] == {"choice": default}
        assert detail["kind"] == kind
    finally:
        await pg_pool.execute("delete from hunts where id = $1", hunt_id)
        await pg_pool.execute("delete from properties where id = $1", property_id)


async def test_timeout_leaves_fresh_checkpoint_parked(pg_pool: asyncpg.Pool) -> None:
    hunt_id, property_id, listing_id, owner_id, job_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    await pg_pool.execute(
        "insert into hunts (id, name, owner_id) values ($1, 'Fresh Checkpoint', $2)",
        hunt_id,
        owner_id,
    )
    await pg_pool.execute(
        "insert into properties (id, name, canonical_address) values ($1, 'Fresh', '2 Clock St')",
        property_id,
    )
    await pg_pool.execute(
        """
        insert into hunt_listings (id, hunt_id, property_id, added_by)
        values ($1, $2, $3, $4)
        """,
        listing_id,
        hunt_id,
        property_id,
        owner_id,
    )
    await pg_pool.execute(
        """
        insert into jobs (id, hunt_id, hunt_listing_id, type, state, payload)
        values ($1, $2, $3, 'ingest', 'waiting_user', $4::jsonb)
        """,
        job_id,
        hunt_id,
        listing_id,
        json.dumps(
            {
                "run_state": {
                    "checkpoint": {
                        "kind": "confirm_value",
                        "question": "Fresh?",
                        "options": ["yes", "no"],
                        "default": "yes",
                    }
                }
            }
        ),
    )
    await pg_pool.execute(
        """
        insert into job_events (job_id, stage, event, at)
        values ($1, 'VERIFY', 'checkpoint_asked', $2)
        """,
        job_id,
        datetime.now(UTC) - timedelta(hours=23),
    )
    try:
        await checkpoint_timeout_tick(pg_pool)
        assert (
            await pg_pool.fetchval("select state from jobs where id = $1", job_id) == "waiting_user"
        )
    finally:
        await pg_pool.execute("delete from hunts where id = $1", hunt_id)
        await pg_pool.execute("delete from properties where id = $1", property_id)
