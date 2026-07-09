"""Projection of the "no available floor plans" state (§8.2, §20) and the
floor_plans upsert idempotency. `_persist_ingest_results` is the worker's write
of a completed ingest; these assert the two behaviours the schema-alignment batch
added:

  * zero scorable plans → the listing is marked `unavailable_at` and the job is
    NOT failed (a legitimate "no availability" result, not an error);
  * a scorable plan clears the marker, and re-running the projection reuses the
    same floor_plan id (upsert on the natural key), so scores stay attached.

Skips without a database, like the other queue tests.
"""

from __future__ import annotations

from uuid import uuid4

import asyncpg
import pytest
from manzil_shared.models import Confidence
from manzil_worker.queue import _persist_ingest_results
from manzil_worker.state import FieldExtraction, FloorPlanIn, PlanScore, RunState, SourceState


async def _seed_listing(pool: asyncpg.Pool) -> tuple:
    hunt_id, property_id, listing_id, user_id = uuid4(), uuid4(), uuid4(), uuid4()
    await pool.execute(
        "insert into hunts (id, name, owner_id) values ($1, 'A', $2)", hunt_id, user_id
    )
    await pool.execute(
        "insert into properties (id, name, canonical_address) values ($1, 'P', 'a')", property_id
    )
    await pool.execute(
        "insert into hunt_listings (id, hunt_id, property_id, added_by) values ($1, $2, $3, $4)",
        listing_id,
        hunt_id,
        property_id,
        user_id,
    )
    return hunt_id, property_id, listing_id


def _state(url: str, floor_plans: list[FloorPlanIn], scores: list[PlanScore]) -> RunState:
    return RunState(
        job_id=uuid4(),
        job_type="ingest",  # type: ignore[arg-type]
        url=url,
        sources=[SourceState(url=url, cleaned_hash="h")],
        reconciled={
            "beds": FieldExtraction(
                value=2, confidence=Confidence.HIGH, model="m", prompt_version=1
            )
        },
        floor_plans=floor_plans,
        scores=scores,
    )


@pytest.mark.asyncio
async def test_no_scorable_plans_marks_unavailable(pg_pool: asyncpg.Pool) -> None:
    hunt_id, property_id, listing_id = await _seed_listing(pg_pool)
    try:
        state = _state("https://x.test/none", floor_plans=[], scores=[])
        async with pg_pool.acquire() as conn, conn.transaction():
            await _persist_ingest_results(
                conn,
                hunt_listing_id=listing_id,
                property_id=property_id,
                rubric_version=0,
                state=state,
            )
        row = await pg_pool.fetchrow(
            "select unavailable_at from hunt_listings where id = $1", listing_id
        )
        assert row["unavailable_at"] is not None  # dimmed, null-score — not an error
        plans = await pg_pool.fetchval(
            "select count(*) from floor_plans where property_id = $1", property_id
        )
        assert plans == 0
    finally:
        await pg_pool.execute("delete from hunts where id = $1", hunt_id)
        await pg_pool.execute("delete from properties where id = $1", property_id)


@pytest.mark.asyncio
async def test_scorable_plan_clears_marker_and_upserts_stable_id(pg_pool: asyncpg.Pool) -> None:
    hunt_id, property_id, listing_id = await _seed_listing(pg_pool)
    try:
        # Pre-mark unavailable so we can prove the projection clears it.
        await pg_pool.execute(
            "update hunt_listings set unavailable_at = now() where id = $1", listing_id
        )
        plan = FloorPlanIn(plan_name="A1", beds=2, baths=2.0, rent_min=1800.0)
        score = PlanScore(plan_name="A1", breakdown={"total": 5.0, "gates": [], "criteria": []})

        async def project() -> None:
            async with pg_pool.acquire() as conn, conn.transaction():
                await _persist_ingest_results(
                    conn,
                    hunt_listing_id=listing_id,
                    property_id=property_id,
                    rubric_version=0,
                    state=_state("https://x.test/one", [plan], [score]),
                )

        await project()
        cleared = await pg_pool.fetchval(
            "select unavailable_at from hunt_listings where id = $1", listing_id
        )
        assert cleared is None  # reversed once a plan was found
        first_id = await pg_pool.fetchval(
            "select id from floor_plans where property_id = $1", property_id
        )

        # Re-ingest the same source/plan: upsert keeps the id (scores stay attached).
        await project()
        ids = await pg_pool.fetch(
            "select id from floor_plans where property_id = $1", property_id
        )
        assert len(ids) == 1
        assert ids[0]["id"] == first_id
        score_count = await pg_pool.fetchval(
            "select count(*) from scores where floor_plan_id = $1", first_id
        )
        assert score_count == 1
    finally:
        await pg_pool.execute("delete from hunts where id = $1", hunt_id)
        await pg_pool.execute("delete from properties where id = $1", property_id)
