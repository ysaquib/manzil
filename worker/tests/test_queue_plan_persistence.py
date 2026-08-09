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
import pytest
from manzil_shared.models import JobState, JobType
from manzil_worker.costs import record_fetch
from manzil_worker.postgres_persistence import PostgresPersistence
from manzil_worker.queue import _make_fresh_source_lookup
from manzil_worker.runner import STAGE_REGISTRY, run_job
from manzil_worker.stages.base import StageCtx
from manzil_worker.stages.plan import plan_stage
from manzil_worker.state import RunState

URL = "https://plan-persist.test/floorplans"


async def _cost_stage(state: RunState, ctx: StageCtx) -> RunState:
    state.cost_usd = 0.0417  # stand in for a real tally
    return state


async def _test_plan_stage(state: RunState, ctx: StageCtx) -> RunState:
    state = await plan_stage(state, ctx)
    assert state.plan is not None
    state.plan.stages = ["PLAN", "cost"]
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


async def test_completed_job_persists_plan_and_cost(
    pg_pool: asyncpg.Pool, monkeypatch: pytest.MonkeyPatch
) -> None:
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

        monkeypatch.setitem(STAGE_REGISTRY, "cost", _cost_stage)
        final = await run_job(state, ctx, [("PLAN", _test_plan_stage), ("cost", _cost_stage)])
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


async def test_stage_costs_land_in_their_own_table(
    pg_pool: asyncpg.Pool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AD-C: `cost_actual_usd` says what the Job cost; `job_stage_costs` says
    which stage cost it. The fetch channel is stored apart from the token
    channel so the Costs view can separate model spend from unblocker spend."""
    property_id, hunt_id, listing_id, job_id = uuid4(), uuid4(), uuid4(), uuid4()
    await _seed(
        pg_pool, property_id=property_id, hunt_id=hunt_id, listing_id=listing_id, job_id=job_id
    )
    try:
        state = RunState(job_id=job_id, job_type=JobType.INGEST, url=URL)
        state.property_id = property_id
        persistence = PostgresPersistence(pg_pool, job_id, ["PLAN", "unblock"], start_cursor=0)
        ctx = StageCtx(
            persistence=persistence, fresh_source_lookup=_make_fresh_source_lookup(pg_pool)
        )

        async def _unblock_stage(state: RunState, ctx: StageCtx) -> RunState:
            record_fetch("brightdata", calls=2)
            return state

        async def _plan_two(state: RunState, ctx: StageCtx) -> RunState:
            state = await plan_stage(state, ctx)
            assert state.plan is not None
            state.plan.stages = ["PLAN", "unblock"]
            return state

        monkeypatch.setitem(STAGE_REGISTRY, "unblock", _unblock_stage)
        final = await run_job(state, ctx, [("PLAN", _plan_two), ("unblock", _unblock_stage)])
        assert final.status is JobState.DONE

        rows = await pg_pool.fetch(
            "select stage, fetch_calls, fetch_cost_usd, llm_cost_usd, fetch_calls_by_provider "
            "from job_stage_costs where job_id = $1 order by stage",
            job_id,
        )
        by_stage = {row["stage"]: row for row in rows}
        assert by_stage["unblock"]["fetch_calls"] == 2
        assert float(by_stage["unblock"]["fetch_cost_usd"]) == 0.003
        assert float(by_stage["unblock"]["llm_cost_usd"]) == 0.0
        assert json.loads(by_stage["unblock"]["fetch_calls_by_provider"]) == {"brightdata": 2}
        # The Job total agrees with the breakdown.
        total = await pg_pool.fetchval("select cost_actual_usd from jobs where id = $1", job_id)
        assert float(total) == 0.003

        # 6 decimals, not 4: a single $0.0015 request must survive the round trip
        # rather than being truncated toward zero.
        await pg_pool.execute(
            "update job_stage_costs set fetch_cost_usd = 0.0015 "
            "where job_id = $1 and stage = 'unblock'",
            job_id,
        )
        stored = await pg_pool.fetchval(
            "select fetch_cost_usd from job_stage_costs where job_id = $1 and stage = 'unblock'",
            job_id,
        )
        assert float(stored) == 0.0015
    finally:
        await pg_pool.execute("delete from job_stage_costs where job_id = $1", job_id)
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
