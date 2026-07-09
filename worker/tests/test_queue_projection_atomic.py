"""P1-2 crash-window fix: the projection (result-row writes) commits in the same
transaction as the DONE flip. A projection failure must roll the terminal state
back — the job never ends `done` with no result rows — and a retry lands both.

Uses PostgresPersistence's `on_done` hook directly with a marker write, so the
atomicity is proven without the full ingest pipeline. Skips without a DB.
"""

from __future__ import annotations

from uuid import uuid4

import asyncpg
import pytest
from manzil_shared.models import JobState, JobType
from manzil_worker.postgres_persistence import PostgresPersistence
from manzil_worker.runner import run_job
from manzil_worker.stages.base import StageCtx
from manzil_worker.state import RunState

STAGE_NAMES = ["only"]


async def _one_stage(state: RunState, ctx: StageCtx) -> RunState:
    return state


async def test_projection_failure_rolls_back_the_done_flip(pg_pool: asyncpg.Pool) -> None:
    job_id = uuid4()
    hunt_id = uuid4()
    await pg_pool.execute(
        "insert into hunts (id, name, owner_id) values ($1, 'test', $2)", hunt_id, uuid4()
    )
    await pg_pool.execute(
        "insert into jobs (id, hunt_id, type, state) values ($1, $2, 'ingest', 'running')",
        job_id,
        hunt_id,
    )
    try:
        attempts: list[int] = []

        async def projection(conn: asyncpg.Connection, state: RunState) -> None:
            # Write a marker, then fail on the first attempt only.
            await conn.execute(
                "insert into job_events (job_id, stage, event) "
                "values ($1, 'projection', 'completed')",
                job_id,
            )
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("projection boom")

        async def marker_count() -> int:
            return await pg_pool.fetchval(
                "select count(*) from job_events where job_id = $1 and stage = 'projection'",
                job_id,
            )

        # First run: projection raises inside the terminal save.
        first = PostgresPersistence(
            pg_pool, job_id, STAGE_NAMES, start_cursor=0, on_done=projection
        )
        state = RunState(job_id=job_id, job_type=JobType.INGEST, url="https://x.test/1")
        with pytest.raises(RuntimeError, match="projection boom"):
            await run_job(state, StageCtx(persistence=first), [("only", _one_stage)])

        # Atomic rollback: not `done`, and the marker the projection wrote is gone.
        row = await pg_pool.fetchrow("select state from jobs where id = $1", job_id)
        assert row["state"] != "done"
        assert await marker_count() == 0

        # Retry: resume from the persisted cursor; projection now succeeds.
        resumed = await PostgresPersistence(pg_pool, job_id, STAGE_NAMES).load(job_id)
        second = PostgresPersistence(
            pg_pool, job_id, STAGE_NAMES, start_cursor=resumed.cursor, on_done=projection
        )
        final = await run_job(resumed, StageCtx(persistence=second), [("only", _one_stage)])

        assert final.status is JobState.DONE
        done = await pg_pool.fetchrow("select state from jobs where id = $1", job_id)
        assert done["state"] == "done"
        assert await marker_count() == 1  # exactly one commit — the successful retry
    finally:
        await pg_pool.execute("delete from jobs where id = $1", job_id)
        await pg_pool.execute("delete from hunts where id = $1", hunt_id)
