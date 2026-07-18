"""P1-2 done-when: a job abandoned mid-run is reclaimed and resumes from its
`current_stage`, not from scratch, within `JOB_ORPHAN_AFTER`.

The kill is simulated by a stage raising CancelledError (the runner does not
catch it, mirroring a hard process death) after earlier stages have persisted.
`locked_at` is time-traveled rather than sleeping five real minutes.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from uuid import uuid4

import asyncpg
import pytest
from manzil_shared.config import MANZIL_JOB_MAX_ATTEMPTS
from manzil_shared.models import JobState, JobType
from manzil_worker.postgres_persistence import PostgresPersistence
from manzil_worker.queue import JOB_ORPHAN_AFTER, claim_next_job, reclaim_orphans
from manzil_worker.runner import run_job
from manzil_worker.stages.base import StageCtx
from manzil_worker.state import RunState

STAGE_NAMES = ["a", "b", "c", "d"]


async def _seed_running_orphan(pool: asyncpg.Pool, *, attempts: int):  # type: ignore[no-untyped-def]
    """A `running` job with a stale heartbeat (orphaned) and a given attempt count."""
    job_id, hunt_id = uuid4(), uuid4()
    await pool.execute(
        "insert into hunts (id, name, owner_id) values ($1, 'test', $2)", hunt_id, uuid4()
    )
    await pool.execute(
        """
        insert into jobs (id, hunt_id, type, state, attempts, locked_by, locked_at)
        values ($1, $2, 'ingest', 'running', $3, 'dead-worker',
                now() - $4::interval)
        """,
        job_id,
        hunt_id,
        attempts,
        JOB_ORPHAN_AFTER + timedelta(seconds=30),
    )
    return job_id, hunt_id


async def test_orphan_at_cap_is_dead_lettered(pg_pool: asyncpg.Pool) -> None:
    job_id, hunt_id = await _seed_running_orphan(pg_pool, attempts=MANZIL_JOB_MAX_ATTEMPTS)
    try:
        async with pg_pool.acquire() as conn:
            reclaimed = await reclaim_orphans(conn)
        assert reclaimed >= 1
        row = await pg_pool.fetchrow(
            "select state, error, finished_at, locked_by, locked_at from jobs where id = $1",
            job_id,
        )
        assert row["state"] == "failed"
        assert row["error"] == f"dead-lettered: orphaned after {MANZIL_JOB_MAX_ATTEMPTS} attempts"
        assert row["finished_at"] is not None
        assert row["locked_by"] is None and row["locked_at"] is None
    finally:
        await pg_pool.execute("delete from hunts where id = $1", hunt_id)


async def test_orphan_below_cap_is_requeued(pg_pool: asyncpg.Pool) -> None:
    job_id, hunt_id = await _seed_running_orphan(pg_pool, attempts=MANZIL_JOB_MAX_ATTEMPTS - 1)
    try:
        async with pg_pool.acquire() as conn:
            reclaimed = await reclaim_orphans(conn)
        assert reclaimed >= 1
        row = await pg_pool.fetchrow(
            "select state, error, finished_at, locked_at from jobs where id = $1", job_id
        )
        assert row["state"] == "queued"  # re-queued, unchanged behavior below the cap
        assert row["error"] is None
        assert row["finished_at"] is None
        assert row["locked_at"] is None
    finally:
        await pg_pool.execute("delete from hunts where id = $1", hunt_id)


async def test_claim_stamps_started_at_once(pg_pool: asyncpg.Pool) -> None:
    job_id, hunt_id = uuid4(), uuid4()
    await pg_pool.execute(
        "insert into hunts (id, name, owner_id) values ($1, 'test', $2)", hunt_id, uuid4()
    )
    await pg_pool.execute(
        "insert into jobs (id, hunt_id, type, state) values ($1, $2, 'ingest', 'queued')",
        job_id,
        hunt_id,
    )
    try:
        async with pg_pool.acquire() as conn:
            first = await claim_next_job(conn, "worker-1")
        assert first is not None and first["started_at"] is not None
        original = first["started_at"]

        # Orphan and reclaim (attempts=1 < cap → re-queued), then claim again.
        await pg_pool.execute(
            "update jobs set locked_at = now() - $2::interval where id = $1",
            job_id,
            JOB_ORPHAN_AFTER + timedelta(seconds=30),
        )
        async with pg_pool.acquire() as conn:
            await reclaim_orphans(conn)
            second = await claim_next_job(conn, "worker-2")
        assert second is not None and second["id"] == job_id
        # coalesce(started_at, now()) — a resume must not reset the metric.
        assert second["started_at"] == original
    finally:
        await pg_pool.execute("delete from hunts where id = $1", hunt_id)


def _stages(executed: list[str], *, crash_at: int | None):  # type: ignore[no-untyped-def]
    out = []
    for index, name in enumerate(STAGE_NAMES):
        if index == crash_at:

            async def crash(state: RunState, ctx: StageCtx) -> RunState:
                raise asyncio.CancelledError

            out.append((name, crash))
        else:

            def make(n: str):  # type: ignore[no-untyped-def]
                async def stage(state: RunState, ctx: StageCtx) -> RunState:
                    executed.append(n)
                    return state

                return stage

            out.append((name, make(name)))
    return out


async def test_orphaned_job_resumes_from_current_stage(pg_pool: asyncpg.Pool) -> None:
    job_id = uuid4()
    hunt_id = uuid4()
    await pg_pool.execute(
        "insert into hunts (id, name, owner_id) values ($1, 'test', $2)", hunt_id, uuid4()
    )
    await pg_pool.execute(
        "insert into jobs (id, hunt_id, type, state) values ($1, $2, 'ingest', 'queued')",
        job_id,
        hunt_id,
    )
    try:
        # First worker claims the job.
        async with pg_pool.acquire() as conn:
            claimed = await claim_next_job(conn, "worker-1")
        assert claimed is not None and claimed["id"] == job_id

        # It runs a, b (persisting each) then dies inside c.
        executed: list[str] = []
        first = PostgresPersistence(pg_pool, job_id, STAGE_NAMES)
        state = RunState(job_id=job_id, job_type=JobType.INGEST, url="https://x.test/1")
        with pytest.raises(asyncio.CancelledError):
            await run_job(state, StageCtx(persistence=first), _stages(executed, crash_at=2))
        assert executed == ["a", "b"]

        row = await pg_pool.fetchrow("select state, current_stage from jobs where id = $1", job_id)
        assert row["state"] == "running"  # still locked — a real crash leaves it so
        assert row["current_stage"] == "c"  # persisted resume point

        # Heartbeat goes stale → the job is an orphan.
        await pg_pool.execute(
            "update jobs set locked_at = now() - $2::interval where id = $1",
            job_id,
            JOB_ORPHAN_AFTER + timedelta(seconds=30),
        )
        async with pg_pool.acquire() as conn:
            reclaimed = await reclaim_orphans(conn)
            assert reclaimed >= 1
            reclaim_row = await claim_next_job(conn, "worker-2")
        assert reclaim_row is not None and reclaim_row["id"] == job_id

        # Second worker rebuilds state and resumes — only c, d run.
        executed.clear()
        resumed_state = await PostgresPersistence(pg_pool, job_id, STAGE_NAMES).load(job_id)
        assert resumed_state.cursor == 2
        second = PostgresPersistence(
            pg_pool, job_id, STAGE_NAMES, start_cursor=resumed_state.cursor
        )
        final = await run_job(
            resumed_state, StageCtx(persistence=second), _stages(executed, crash_at=None)
        )

        assert executed == ["c", "d"]  # resumed from current_stage, not from scratch
        assert final.status is JobState.DONE
        done = await pg_pool.fetchrow("select state from jobs where id = $1", job_id)
        assert done["state"] == "done"
    finally:
        await pg_pool.execute("delete from jobs where id = $1", job_id)
        await pg_pool.execute("delete from hunts where id = $1", hunt_id)
