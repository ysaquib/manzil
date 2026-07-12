"""P3-2: the terminal projection persists the §10.4 manifest and the cost tally.

Asserts a completed ingest job row carries `plan` jsonb matching `state.plan`
and `cost_actual_usd == state.cost_usd`, and that PLAN's DB-backed
`fresh_source_lookup` plans `skip: hash_fresh` against a real fresh
`property_sources` row. Skips without a database (conftest `pg_pool`).
"""

from __future__ import annotations

import json
from uuid import uuid4

import asyncpg
from manzil_shared.models import JobState, JobType
from manzil_worker.postgres_persistence import PostgresPersistence
from manzil_worker.queue import _make_fresh_source_lookup
from manzil_worker.runner import run_job
from manzil_worker.stages.base import StageCtx
from manzil_worker.stages.plan import plan_stage
from manzil_worker.state import RunState

URL = "https://plan-persist.test/floorplans"


async def _cost_stage(state: RunState, ctx: StageCtx) -> RunState:
    state.cost_usd = 0.0417  # stand in for a real tally
    return state


async def _seed(pool: asyncpg.Pool, *, property_id, hunt_id, listing_id, job_id) -> None:
    await pool.execute(
        "insert into hunts (id, name, owner_id) values ($1, 't', $2)", hunt_id, uuid4()
    )
    await pool.execute(
        "insert into properties (id, name, canonical_address) values ($1, 'P', 'A')", property_id
    )
    await pool.execute(
        "insert into hunt_listings (id, hunt_id, property_id, added_by) values ($1, $2, $3, $4)",
        listing_id,
        hunt_id,
        property_id,
        uuid4(),
    )
    await pool.execute(
        "insert into jobs (id, hunt_id, hunt_listing_id, type, state) "
        "values ($1, $2, $3, 'ingest', 'running')",
        job_id,
        hunt_id,
        listing_id,
    )


async def _cleanup(pool: asyncpg.Pool, *, property_id, hunt_id, job_id) -> None:
    await pool.execute("delete from jobs where id = $1", job_id)
    await pool.execute("delete from property_sources where property_id = $1", property_id)
    await pool.execute("delete from hunt_listings where property_id = $1", property_id)
    await pool.execute("delete from properties where id = $1", property_id)
    await pool.execute("delete from hunts where id = $1", hunt_id)


async def test_completed_job_persists_plan_and_cost(pg_pool: asyncpg.Pool) -> None:
    property_id, hunt_id, listing_id, job_id = uuid4(), uuid4(), uuid4(), uuid4()
    await _seed(
        pg_pool, property_id=property_id, hunt_id=hunt_id, listing_id=listing_id, job_id=job_id
    )
    try:
        state = RunState(job_id=job_id, job_type=JobType.INGEST, url=URL)
        state.property_id = property_id
        persistence = PostgresPersistence(pg_pool, job_id, ["PLAN", "cost"], start_cursor=0)
        ctx = StageCtx(
            persistence=persistence, fresh_source_lookup=_make_fresh_source_lookup(pg_pool)
        )

        final = await run_job(state, ctx, [("PLAN", plan_stage), ("cost", _cost_stage)])
        assert final.status is JobState.DONE
        assert final.plan is not None

        row = await pg_pool.fetchrow("select plan, cost_actual_usd from jobs where id = $1", job_id)
        # plan jsonb matches the manifest (clean, null-free shape the UI renders).
        assert json.loads(row["plan"]) == final.plan.model_dump(mode="json", exclude_none=True)
        assert json.loads(row["plan"])["sources"][0]["action"] == "fetch"
        # cost_actual_usd == the in-memory tally (NFR1 is measured from this column).
        assert float(row["cost_actual_usd"]) == final.cost_usd == 0.0417
    finally:
        await _cleanup(pg_pool, property_id=property_id, hunt_id=hunt_id, job_id=job_id)


async def test_db_lookup_plans_skip_on_fresh_source(pg_pool: asyncpg.Pool) -> None:
    property_id, hunt_id, listing_id, job_id = uuid4(), uuid4(), uuid4(), uuid4()
    await _seed(
        pg_pool, property_id=property_id, hunt_id=hunt_id, listing_id=listing_id, job_id=job_id
    )
    try:
        await pg_pool.execute(
            """
            insert into property_sources
                (property_id, url, site_domain, cleaned_text, cleaned_text_hash,
                 last_fetched_at, last_success_at)
            values ($1, $2, 'plan-persist.test', 'persisted body', 'hash-xyz', now(), now())
            """,
            property_id,
            URL,
        )
        state = RunState(job_id=job_id, job_type=JobType.INGEST, url=URL)
        state.property_id = property_id
        ctx = StageCtx(fresh_source_lookup=_make_fresh_source_lookup(pg_pool))

        out = await plan_stage(state, ctx)
        assert out.plan is not None
        assert out.plan.sources[0].action == "skip"
        assert out.plan.sources[0].why == "hash_fresh"
        assert out.sources[0].cleaned_text == "persisted body"
    finally:
        await _cleanup(pg_pool, property_id=property_id, hunt_id=hunt_id, job_id=job_id)
