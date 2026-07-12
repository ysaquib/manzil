"""P3-2 regression: a pre-P3 RunState snapshot (`plan is None`, integer cursor
indexing the legacy 6-stage list) MUST resume through the ingest dispatcher on
the legacy `PHASE0_STAGES` walk — not the PLAN-prepended `INGEST_STAGES`, which
would offset the cursor by one and re-run an already-passed stage.

Driven at the dispatcher level (not `run_job` with an explicit stages arg) so it
covers the dispatcher's walk-selection. Skips without a database.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import asyncpg
from manzil_shared.models import FetchOutcome, JobState, JobType
from manzil_worker.queue import make_ingest_dispatcher
from manzil_worker.state import RunState, SourceState
from worker_helpers import PAGES, FakeFetcher, FakeLLM, maple_extraction

URL = "https://maplecourt.test/floorplans"
VALIDATE_YES = {
    "is_listing": True,
    "property_name": "Maple Court Apartments",
    "reason": "single property advertised with plans and rent",
}


async def _seed(pool: asyncpg.Pool, *, property_id, hunt_id, listing_id, job_id, body) -> None:
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
    # Pre-P3 snapshot: plan is None, cursor=3 (validate_url/fetch/validate done),
    # extract/verify/score remain — indexing the legacy 6-stage list.
    snapshot = RunState(
        job_id=job_id,
        job_type=JobType.INGEST,
        url=URL,
        cursor=3,
        status=JobState.RUNNING,
        sources=[
            SourceState(
                url=URL,
                tier_used=1,
                outcome=FetchOutcome.SUCCESS,
                cleaned_text=body,
                cleaned_hash="h",
            )
        ],
    )
    assert snapshot.plan is None
    await pool.execute(
        """
        insert into jobs (id, hunt_id, hunt_listing_id, type, state, current_stage, payload)
        values ($1, $2, $3, 'ingest', 'running', 'extract', $4)
        """,
        job_id,
        hunt_id,
        listing_id,
        json.dumps({"run_state": snapshot.model_dump(mode="json")}),
    )


async def test_pre_p3_snapshot_resumes_on_legacy_list(pg_pool: asyncpg.Pool) -> None:
    property_id, hunt_id, listing_id, job_id = uuid4(), uuid4(), uuid4(), uuid4()
    body = (Path(PAGES) / "e2e_listing.html").read_text()
    await _seed(
        pg_pool,
        property_id=property_id,
        hunt_id=hunt_id,
        listing_id=listing_id,
        job_id=job_id,
        body=body,
    )
    try:
        llm = FakeLLM(
            {
                "validate": VALIDATE_YES,
                "extract": maple_extraction(),
                "verify": {"contradictions": []},
            }
        )
        dispatch = make_ingest_dispatcher(
            dsn=None,
            fetchers_factory=lambda: {1: FakeFetcher(1, body)},  # type: ignore[dict-item]
            call_structured=llm,
        )
        job = await pg_pool.fetchrow("select * from jobs where id = $1", job_id)
        await dispatch(pg_pool, job)

        # Resumed at EXTRACT: validate is NOT re-run (the off-by-one bug would have
        # resumed at VALIDATE), and PLAN never executes on the legacy walk.
        assert [stage for stage, _ in llm.calls] == ["extract", "verify"]

        row = await pg_pool.fetchrow("select state, plan from jobs where id = $1", job_id)
        assert row["state"] == "done"
        assert row["plan"] is None  # a pre-P3 job never builds a manifest

        # Labels stay legacy lowercase; no PLAN row, no re-completed validate.
        completed = await pg_pool.fetch(
            "select stage from job_events where job_id = $1 and event = 'completed'", job_id
        )
        stages = {r["stage"] for r in completed}
        assert stages == {"extract", "verify", "score"}
        assert "PLAN" not in stages and "validate" not in stages
    finally:
        await pg_pool.execute("delete from scores where hunt_listing_id = $1", listing_id)
        await pg_pool.execute("delete from job_events where job_id = $1", job_id)
        await pg_pool.execute("delete from jobs where id = $1", job_id)
        await pg_pool.execute("delete from floor_plans where property_id = $1", property_id)
        await pg_pool.execute("delete from extractions where property_id = $1", property_id)
        await pg_pool.execute("delete from property_sources where property_id = $1", property_id)
        await pg_pool.execute("delete from hunt_listings where id = $1", listing_id)
        await pg_pool.execute("delete from properties where id = $1", property_id)
        await pg_pool.execute("delete from hunts where id = $1", hunt_id)
