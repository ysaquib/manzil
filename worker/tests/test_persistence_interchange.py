"""P1-2: PostgresPersistence is interchangeable with FilePersistence.

One test body runs against both behind the `Persistence` protocol: `save(state)`
must round-trip a RunState back out (via each sink's `load`). The Postgres
variant skips cleanly when the DB is unreachable, following
test_migration_0002_schema.py's guard.
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio
from manzil_shared.models import Confidence, FetchOutcome, JobState, JobType
from manzil_worker.persistence import FilePersistence
from manzil_worker.postgres_persistence import PostgresPersistence
from manzil_worker.state import FieldExtraction, RunState, SourceState

# Defined inline (not imported from conftest) so a sibling test package's
# same-named conftest can never shadow it — see test_migration_0002_schema.py.
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
)
STAGE_NAMES = ["validate_url", "fetch", "validate", "extract", "verify", "score"]


def _sample_state(job_id) -> RunState:  # type: ignore[no-untyped-def]
    state = RunState(job_id=job_id, job_type=JobType.INGEST, url="https://x.test/1")
    state.cursor = 4  # mid-run: outputs of the first four stages are durable
    state.status = JobState.RUNNING
    state.cost_usd = 0.4217
    state.sources = [
        SourceState(
            url="https://x.test/1",
            tier_used=1,
            outcome=FetchOutcome.SUCCESS,
            cleaned_text="two bedroom apartment",
            cleaned_hash="deadbeef",
        )
    ]
    state.extractions = {
        "beds": [
            FieldExtraction(value=2, confidence=Confidence.HIGH, model="m", prompt_version=1)
        ]
    }
    return state


@pytest_asyncio.fixture(params=["file", "postgres"])
async def persistence_case(request, tmp_path: Path):  # type: ignore[no-untyped-def]
    """Yields (job_id, persistence, readback). `readback()` reconstructs the
    RunState from whatever sink this parametrization uses."""
    job_id = uuid4()
    if request.param == "file":
        sink = FilePersistence(tmp_path)

        async def readback() -> RunState:
            return sink.load(job_id)

        yield job_id, sink, readback
        return

    try:
        pool = await asyncpg.create_pool(DATABASE_URL, timeout=5, min_size=1, max_size=2)
    except (OSError, asyncpg.PostgresError) as exc:  # pragma: no cover - env guard
        pytest.skip(f"Postgres unreachable at {DATABASE_URL}: {exc}")
    hunt_id = uuid4()
    try:
        await pool.execute(
            "insert into hunts (id, name, owner_id) values ($1, 'test', $2)", hunt_id, uuid4()
        )
        await pool.execute(
            "insert into jobs (id, hunt_id, type, state) values ($1, $2, 'ingest', 'queued')",
            job_id,
            hunt_id,
        )
        pg_sink = PostgresPersistence(pool, job_id, STAGE_NAMES)

        async def readback() -> RunState:
            return await pg_sink.load(job_id)

        yield job_id, pg_sink, readback
        await pool.execute("delete from jobs where id = $1", job_id)
        await pool.execute("delete from hunts where id = $1", hunt_id)
    finally:
        await pool.close()


async def test_save_round_trips_run_state(persistence_case) -> None:  # type: ignore[no-untyped-def]
    job_id, persistence, readback = persistence_case
    state = _sample_state(job_id)

    await persistence.save(state)
    loaded = await readback()

    assert loaded.job_id == job_id
    assert loaded.cursor == 4
    assert loaded.url == "https://x.test/1"
    assert loaded.status is JobState.RUNNING
    assert loaded.cost_usd == pytest.approx(0.4217)
    assert loaded.sources[0].cleaned_hash == "deadbeef"
    assert loaded.extractions["beds"][0].value == 2
    assert loaded.extractions["beds"][0].confidence is Confidence.HIGH


async def test_save_reflects_the_cursor_it_was_called_with(persistence_case) -> None:  # type: ignore[no-untyped-def]
    # Persist-before-advance: a save at cursor N lands cursor N, never N+1.
    job_id, persistence, readback = persistence_case
    state = _sample_state(job_id)
    state.cursor = 2

    await persistence.save(state)

    assert (await readback()).cursor == 2
