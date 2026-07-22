"""P3-4 done-when: DEDUPE merge through the durable queue, end to end.

Two DB-backed cases (skip cleanly without the local Supabase Postgres, like the
other queue tests):

1. A second URL for a building already known as property P1 parks at a
   `resolve_dedupe` checkpoint; answering "merge" re-points everything onto P1
   and drops the placeholder P2 — one property, both sources, both re-pointed.
2. Resume-clobber regression: a snapshot parked AFTER a DEDUPE merge (property_id
   already switched to the canonical P1, cursor past DEDUPE) must keep its
   canonical property_id on resume — the dispatcher must not reset it to the
   placeholder P2 (the queue.py fix).
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import asyncpg
from manzil_shared.models import JobState, JobType
from manzil_worker.fetching.registry import InMemoryRegistry
from manzil_worker.phase0_rubric import PHASE0_RUBRIC_VERSION, phase0_rubric
from manzil_worker.queue import make_ingest_dispatcher
from manzil_worker.runner import INGEST_STAGE_NAMES, INGEST_STAGES, run_job
from manzil_worker.stages.base import StageCtx
from manzil_worker.state import DedupeDecision, GeocodeIn, RunState
from worker_helpers import PAGES, FakeFetcher, FakeLLM, empty_discovery_agent, maple_extraction

URL_A = "https://maplecourt.test/official"  # P1's already-known source
URL_B = "https://aggregator.test/maple-court"  # the second URL we submit
P1_PLACE, P1_LAT, P1_LNG = "place-maple-court", 42.3314, -83.0458

VALIDATE_YES = {
    "is_listing": True,
    "property_name": "Maple Court Apartments",
    "reason": "single property advertised with plans and rent",
}


async def _fake_geocode(address: str) -> GeocodeIn:
    # Both URLs resolve to P1's mapped place (CI never touches Google).
    return GeocodeIn(place_id=P1_PLACE, lat=P1_LAT, lng=P1_LNG, formatted_address=address)


def _handlers() -> FakeLLM:
    # EXTRACT emits a slightly-different name than P1 (gray-zone similarity → the
    # checkpoint branch); same address so it maps to the same place.
    extraction = maple_extraction()
    extraction["property_identity"] = {
        "name": "Maple Court Apts",  # token_sort_ratio ~84 vs "Maple Court Apartments"
        "address": "120 Maple Court Dr, Detroit, MI 48201",
        "official_url": None,
    }
    return FakeLLM(
        {"validate": VALIDATE_YES, "extract": extraction, "verify": {"contradictions": []}}
    )


async def _seed_canonical_and_placeholder(
    pool: asyncpg.Pool, *, hunt_id, p1, p2, listing_id, job_id
):
    body = (Path(PAGES) / "e2e_listing.html").read_text()
    await pool.execute(
        "insert into hunts (id, name, owner_id) values ($1, 't', $2)", hunt_id, uuid4()
    )
    # P1: the canonical property, already geocoded, with one known source.
    await pool.execute(
        """
        insert into properties (id, name, canonical_address, place_id, lat, lng)
        values ($1, 'Maple Court Apartments', '120 Maple Court Dr, Detroit, MI 48201', $2, $3, $4)
        """,
        p1,
        P1_PLACE,
        P1_LAT,
        P1_LNG,
    )
    await pool.execute(
        """
        insert into property_sources
            (property_id, url, site_domain, cleaned_text_hash, last_success_at)
        values ($1, $2, 'maplecourt.test', 'h', now())
        """,
        p1,
        URL_A,
    )
    # P2: the fresh placeholder the second submission created (submit_listing).
    await pool.execute(
        "insert into properties (id, name, canonical_address) values ($1, $2, $2)", p2, URL_B
    )
    await pool.execute(
        "insert into hunt_listings (id, hunt_id, property_id, added_by) values ($1, $2, $3, $4)",
        listing_id,
        hunt_id,
        p2,
        uuid4(),
    )
    await pool.execute(
        "insert into jobs (id, hunt_id, hunt_listing_id, type, state, payload) "
        "values ($1, $2, $3, 'ingest', 'queued', $4)",
        job_id,
        hunt_id,
        listing_id,
        json.dumps({"url": URL_B}),
    )
    return body


async def _cleanup(pool: asyncpg.Pool, *, hunt_id, p1, p2, job_id, listing_id):
    await pool.execute("delete from scores where hunt_listing_id = $1", listing_id)
    await pool.execute("delete from job_events where job_id = $1", job_id)
    await pool.execute("delete from jobs where id = $1", job_id)
    for pid in (p1, p2):
        await pool.execute("delete from floor_plans where property_id = $1", pid)
        await pool.execute("delete from extractions where property_id = $1", pid)
        await pool.execute("delete from property_sources where property_id = $1", pid)
    await pool.execute("delete from hunt_listings where id = $1", listing_id)
    for pid in (p1, p2):
        await pool.execute("delete from properties where id = $1", pid)
    await pool.execute("delete from hunts where id = $1", hunt_id)


async def test_second_url_merges_into_canonical_via_checkpoint(pg_pool: asyncpg.Pool) -> None:
    hunt_id, p1, p2, listing_id, job_id = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    body = await _seed_canonical_and_placeholder(
        pg_pool, hunt_id=hunt_id, p1=p1, p2=p2, listing_id=listing_id, job_id=job_id
    )
    try:
        dispatch = make_ingest_dispatcher(
            dsn=None,
            fetchers_factory=lambda: {1: FakeFetcher(1, body)},  # type: ignore[dict-item]
            call_structured=_handlers(),
            call_agent=empty_discovery_agent,
            geocode_address=_fake_geocode,
        )
        job = await pg_pool.fetchrow("select * from jobs where id = $1", job_id)
        await dispatch(pg_pool, job)

        # Parked at the resolve_dedupe checkpoint naming P1 as the merge target.
        row = await pg_pool.fetchrow("select state, payload from jobs where id = $1", job_id)
        assert row["state"] == JobState.WAITING_USER.value
        prompt = json.loads(row["payload"])["run_state"]["checkpoint"]
        assert prompt["kind"] == "resolve_dedupe"
        assert prompt["default"] == "keep_separate"
        assert prompt["context_ref"] == str(p1)

        # Answer "merge" the way the API does: stash the answer, clear the prompt,
        # flip the job back to queued.
        payload = json.loads(row["payload"])
        run_state = payload["run_state"]
        payload["checkpoint_answer"] = {"choice": "merge", "context_ref": prompt["context_ref"]}
        run_state["checkpoint"] = None
        run_state["status"] = JobState.RUNNING.value
        payload["run_state"] = run_state
        await pg_pool.execute(
            "update jobs set state = 'queued', payload = $2 where id = $1",
            job_id,
            json.dumps(payload),
        )

        job = await pg_pool.fetchrow("select * from jobs where id = $1", job_id)
        await dispatch(pg_pool, job)

        # One property survives (P2 deleted); both sources + extractions on P1; the
        # listing re-pointed; job done.
        assert await pg_pool.fetchval("select 1 from properties where id = $1", p2) is None
        assert await pg_pool.fetchval("select count(*) from properties where id = $1", p1) == 1
        urls = await pg_pool.fetch(
            "select url from property_sources where property_id = $1 order by url", p1
        )
        assert [r["url"] for r in urls] == [URL_B, URL_A]
        listing_prop = await pg_pool.fetchval(
            "select property_id from hunt_listings where id = $1", listing_id
        )
        assert listing_prop == p1
        ext_count = await pg_pool.fetchval(
            "select count(*) from extractions where property_id = $1", p1
        )
        assert ext_count > 0
        assert await pg_pool.fetchval("select state from jobs where id = $1", job_id) == "done"
    finally:
        await _cleanup(pg_pool, hunt_id=hunt_id, p1=p1, p2=p2, job_id=job_id, listing_id=listing_id)


async def test_resume_after_merge_keeps_canonical_property_id(pg_pool: asyncpg.Pool) -> None:
    hunt_id, p1, p2, listing_id, job_id = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    body = await _seed_canonical_and_placeholder(
        pg_pool, hunt_id=hunt_id, p1=p1, p2=p2, listing_id=listing_id, job_id=job_id
    )
    try:
        # Build a realistic full RunState by running the ingest walk once with NO
        # candidates (so it does not merge and stays on P2), then hand-edit it into
        # a "parked just after a merge" snapshot: property_id = canonical P1, cursor
        # at VERIFY (past DEDUPE).
        base = RunState(job_id=job_id, job_type=JobType.INGEST, url=URL_B)
        base.property_id = p2
        ctx = StageCtx(
            fetchers={1: FakeFetcher(1, body)},  # type: ignore[dict-item]
            registry=InMemoryRegistry(),
            call_structured=_handlers(),
            call_agent=empty_discovery_agent,
            rubric=phase0_rubric(),
            rubric_version=PHASE0_RUBRIC_VERSION,
            geocode_address=_fake_geocode,  # no candidates seam → no merge
        )
        base = await run_job(base, ctx, INGEST_STAGES)
        assert base.status is JobState.DONE and base.property_id == p2

        base.property_id = p1  # a merge switched the run to the canonical property
        base.dedupe = DedupeDecision(action="merged_auto", candidate_property_id=str(p1))
        base.status = JobState.RUNNING
        base.cursor = INGEST_STAGE_NAMES.index("VERIFY")  # resume past DEDUPE
        await pg_pool.execute(
            "update jobs set state = 'queued', current_stage = 'VERIFY', "
            "payload = $2 where id = $1",
            job_id,
            json.dumps({"url": URL_B, "run_state": base.model_dump(mode="json")}),
        )

        dispatch = make_ingest_dispatcher(
            dsn=None,
            fetchers_factory=lambda: {1: FakeFetcher(1, body)},  # type: ignore[dict-item]
            call_structured=_handlers(),
            call_agent=empty_discovery_agent,
            geocode_address=_fake_geocode,
        )
        job = await pg_pool.fetchrow("select * from jobs where id = $1", job_id)
        await dispatch(pg_pool, job)

        # The dispatcher did NOT clobber property_id back to P2: the run merged onto
        # P1, so P2 is gone and the listing points at P1.
        assert await pg_pool.fetchval("select 1 from properties where id = $1", p2) is None
        listing_prop = await pg_pool.fetchval(
            "select property_id from hunt_listings where id = $1", listing_id
        )
        assert listing_prop == p1
        assert await pg_pool.fetchval("select state from jobs where id = $1", job_id) == "done"
        snapshot = json.loads(
            await pg_pool.fetchval("select payload from jobs where id = $1", job_id)
        )["run_state"]
        assert snapshot["property_id"] == str(p1)
    finally:
        await _cleanup(pg_pool, hunt_id=hunt_id, p1=p1, p2=p2, job_id=job_id, listing_id=listing_id)
