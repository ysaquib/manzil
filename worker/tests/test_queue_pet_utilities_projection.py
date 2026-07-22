"""§9.5 v1 persistence: EXTRACT's pet-costs block projects onto the fee_checklist
pet slots (never clobbering a human 'manual' entry) and the utilities-included
block lands as one append-only `utilities_included` extraction. Skips cleanly
without Postgres like its queue-test neighbors (test_queue_identity_projection)."""

from __future__ import annotations

import json
from uuid import uuid4

import asyncpg
from manzil_shared.models import FetchOutcome, JobType
from manzil_worker.queue import _persist_ingest_results
from manzil_worker.state import PetCostsIn, RunState, SourceState, UtilitiesIn


async def _seed(pool: asyncpg.Pool) -> tuple:  # type: ignore[no-untyped-def]
    hunt_id, property_id, listing_id = uuid4(), uuid4(), uuid4()
    await pool.execute(
        "insert into hunts (id, name, owner_id) values ($1, 'test', $2)", hunt_id, uuid4()
    )
    await pool.execute(
        "insert into properties (id, name, canonical_address) values ($1, 'P', 'addr')",
        property_id,
    )
    await pool.execute(
        "insert into hunt_listings (id, hunt_id, property_id, added_by) values ($1, $2, $3, $4)",
        listing_id,
        hunt_id,
        property_id,
        uuid4(),
    )
    return hunt_id, property_id, listing_id


async def _cleanup(pool: asyncpg.Pool, hunt_id, property_id) -> None:  # type: ignore[no-untyped-def]
    await pool.execute("delete from hunts where id = $1", hunt_id)
    await pool.execute("delete from properties where id = $1", property_id)


def _state(
    *,
    pet_costs: PetCostsIn | None = None,
    utilities: UtilitiesIn | None = None,
) -> RunState:
    url = f"https://x.test/{uuid4()}"
    state = RunState(job_id=uuid4(), job_type=JobType.INGEST, url=url)
    state.sources = [
        SourceState(
            url=url, tier_used=1, outcome=FetchOutcome.SUCCESS, cleaned_text="x", cleaned_hash="h"
        )
    ]
    state.pet_costs = pet_costs
    state.utilities = utilities
    return state


async def _run(pool: asyncpg.Pool, listing_id, property_id, state: RunState) -> None:  # type: ignore[no-untyped-def]
    async with pool.acquire() as conn, conn.transaction():
        await _persist_ingest_results(
            conn,
            hunt_listing_id=listing_id,
            property_id=property_id,
            rubric_version=1,
            state=state,
        )


async def test_pet_slots_written_for_non_null_amounts_only(pg_pool: asyncpg.Pool) -> None:
    hunt_id, property_id, listing_id = await _seed(pg_pool)
    try:
        state = _state(
            pet_costs=PetCostsIn(
                cat_rent_monthly=20.0,
                dog_rent_monthly=35.0,
                pet_rent_monthly=None,
                evidence_quote="Cat $20, dog $35",
            )
        )
        await _run(pg_pool, listing_id, property_id, state)

        rows = {
            r["fee_slot"]: r
            for r in await pg_pool.fetch(
                "select fee_slot, amount, value_state, evidence_ref from fee_checklist "
                "where hunt_listing_id = $1",
                listing_id,
            )
        }
        assert set(rows) == {"pet_rent_cat", "pet_rent_dog"}  # generic null → not written
        assert float(rows["pet_rent_cat"]["amount"]) == 20.0
        assert rows["pet_rent_cat"]["value_state"] == "extracted"
        assert rows["pet_rent_cat"]["evidence_ref"] == "Cat $20, dog $35"
        assert float(rows["pet_rent_dog"]["amount"]) == 35.0
    finally:
        await _cleanup(pg_pool, hunt_id, property_id)


async def test_extracted_pet_rent_never_clobbers_manual(pg_pool: asyncpg.Pool) -> None:
    hunt_id, property_id, listing_id = await _seed(pg_pool)
    try:
        # A human manual entry exists for the cat slot.
        await pg_pool.execute(
            """
            insert into fee_checklist (hunt_listing_id, fee_slot, amount, value_state)
            values ($1, 'pet_rent_cat', 99.00, 'manual')
            """,
            listing_id,
        )
        state = _state(pet_costs=PetCostsIn(cat_rent_monthly=20.0))
        await _run(pg_pool, listing_id, property_id, state)

        row = await pg_pool.fetchrow(
            "select amount, value_state from fee_checklist "
            "where hunt_listing_id = $1 and fee_slot = 'pet_rent_cat'",
            listing_id,
        )
        assert float(row["amount"]) == 99.0  # human wins
        assert row["value_state"] == "manual"
    finally:
        await _cleanup(pg_pool, hunt_id, property_id)


async def test_extracted_pet_rent_updates_prior_extracted(pg_pool: asyncpg.Pool) -> None:
    hunt_id, property_id, listing_id = await _seed(pg_pool)
    try:
        for amount in (20, 25):
            state = _state(pet_costs=PetCostsIn(cat_rent_monthly=amount))
            await _run(pg_pool, listing_id, property_id, state)
        row = await pg_pool.fetchrow(
            "select amount from fee_checklist "
            "where hunt_listing_id = $1 and fee_slot = 'pet_rent_cat'",
            listing_id,
        )
        assert float(row["amount"]) == 25.0  # re-ingest refreshes the extracted amount
    finally:
        await _cleanup(pg_pool, hunt_id, property_id)


async def test_utilities_included_lands_as_one_extraction(pg_pool: asyncpg.Pool) -> None:
    hunt_id, property_id, listing_id = await _seed(pg_pool)
    try:
        state = _state(
            utilities=UtilitiesIn(
                included=["water", "trash"], evidence_quote="Water & trash included"
            )
        )
        await _run(pg_pool, listing_id, property_id, state)

        row = await pg_pool.fetchrow(
            "select value, confidence, evidence_quote, hunt_id, model from extractions "
            "where property_id = $1 and criterion_key = 'utilities_included'",
            property_id,
        )
        assert row is not None
        assert json.loads(row["value"]) == ["water", "trash"]
        assert row["confidence"] == "high"
        assert row["evidence_quote"] == "Water & trash included"
        assert row["hunt_id"] is None
        assert row["model"]  # NOT NULL provenance is populated
    finally:
        await _cleanup(pg_pool, hunt_id, property_id)


async def test_empty_utilities_list_still_writes_extraction(pg_pool: asyncpg.Pool) -> None:
    """included == [] means the page states none are included — a real fact, so
    the row is written; only included is None (page silent) skips the write."""
    hunt_id, property_id, listing_id = await _seed(pg_pool)
    try:
        await _run(pg_pool, listing_id, property_id, _state(utilities=UtilitiesIn(included=[])))
        count = await pg_pool.fetchval(
            "select count(*) from extractions "
            "where property_id = $1 and criterion_key = 'utilities_included'",
            property_id,
        )
        # Append-only truth stores the Source candidate and its resolved row;
        # current_extractions still exposes one effective resolution.
        assert count == 2
        assert (
            await pg_pool.fetchval(
                "select count(*) from current_extractions "
                "where property_id = $1 and criterion_key = 'utilities_included'",
                property_id,
            )
            == 1
        )
    finally:
        await _cleanup(pg_pool, hunt_id, property_id)


async def test_no_pet_or_utilities_blocks_writes_nothing(pg_pool: asyncpg.Pool) -> None:
    hunt_id, property_id, listing_id = await _seed(pg_pool)
    try:
        await _run(pg_pool, listing_id, property_id, _state())
        fees = await pg_pool.fetchval(
            "select count(*) from fee_checklist where hunt_listing_id = $1", listing_id
        )
        utils = await pg_pool.fetchval(
            "select count(*) from extractions "
            "where property_id = $1 and criterion_key = 'utilities_included'",
            property_id,
        )
        assert fees == 0
        assert utils == 0
    finally:
        await _cleanup(pg_pool, hunt_id, property_id)
