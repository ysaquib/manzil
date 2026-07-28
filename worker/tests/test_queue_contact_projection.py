"""P3-21 persistence: contact observations land append-only with the right
provenance, and `property_contacts_current` resolves them by precedence.

Skips cleanly without Postgres like its queue-test neighbors
(test_queue_pet_utilities_projection).
"""

from __future__ import annotations

from uuid import uuid4

import asyncpg
from manzil_shared.models import FetchOutcome, JobType
from manzil_worker.queue import _persist_ingest_results
from manzil_worker.state import PropertyContactIn, PropertyIdentityIn, RunState, SourceState

OFFICIAL = "https://maplecourt.test"


async def _seed(pool: asyncpg.Pool) -> tuple:  # type: ignore[no-untyped-def]
    hunt_id, property_id, listing_id = uuid4(), uuid4(), uuid4()
    await pool.execute(
        "insert into hunts (id, name, owner_id) values ($1, 'test', $2)", hunt_id, uuid4()
    )
    await pool.execute(
        "insert into properties (id, name, canonical_address, official_url) "
        "values ($1, 'P', 'addr', $2)",
        property_id,
        OFFICIAL,
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
    url: str,
    property_contact: PropertyContactIn | None = None,
    maps_contact: PropertyContactIn | None = None,
    official_source_url: str | None = None,
) -> RunState:
    state = RunState(job_id=uuid4(), job_type=JobType.INGEST, url=url)
    state.sources = [
        SourceState(
            url=url, tier_used=1, outcome=FetchOutcome.SUCCESS, cleaned_text="x", cleaned_hash="h"
        )
    ]
    state.property_identity = PropertyIdentityIn(official_url=OFFICIAL)
    state.property_contact = property_contact
    state.maps_contact = maps_contact
    state.official_source_url = official_source_url
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


async def _contacts(pool: asyncpg.Pool, property_id) -> dict:  # type: ignore[no-untyped-def]
    rows = await pool.fetch(
        "select kind, value, provenance from property_contacts_current where property_id = $1",
        property_id,
    )
    return {r["kind"]: (r["value"], r["provenance"]) for r in rows}


async def test_official_source_contact_outranks_places(pg_pool: asyncpg.Pool) -> None:
    """The top rung: when the fetched page IS the official site, its number wins
    over Google's — no voting, just precedence."""
    hunt_id, property_id, listing_id = await _seed(pg_pool)
    try:
        url = f"{OFFICIAL}/floorplans"
        state = _state(
            url=url,
            official_source_url=url,
            property_contact=PropertyContactIn(phone="313-555-0142"),
            maps_contact=PropertyContactIn(phone="(313) 555-9999"),
        )
        await _run(pg_pool, listing_id, property_id, state)

        current = await _contacts(pg_pool, property_id)
        assert current["phone"] == ("(313) 555-0142", "official_site")
        # Both observations are retained — precedence resolves, it never deletes.
        total = await pg_pool.fetchval(
            "select count(*) from property_contacts where property_id = $1 and kind = 'phone'",
            property_id,
        )
        assert total == 2
    finally:
        await _cleanup(pg_pool, hunt_id, property_id)


async def test_places_outranks_a_plain_listing(pg_pool: asyncpg.Pool) -> None:
    hunt_id, property_id, listing_id = await _seed(pg_pool)
    try:
        state = _state(
            url=f"https://aggregator.test/{uuid4()}",  # not the official site
            property_contact=PropertyContactIn(phone="313-555-0142"),
            maps_contact=PropertyContactIn(phone="(313) 555-9999"),
        )
        await _run(pg_pool, listing_id, property_id, state)

        current = await _contacts(pg_pool, property_id)
        assert current["phone"] == ("(313) 555-9999", "google_places")
    finally:
        await _cleanup(pg_pool, hunt_id, property_id)


async def test_listing_contact_is_the_last_rung(pg_pool: asyncpg.Pool) -> None:
    hunt_id, property_id, listing_id = await _seed(pg_pool)
    try:
        state = _state(
            url=f"https://aggregator.test/{uuid4()}",
            property_contact=PropertyContactIn(phone="313-555-0142"),
        )
        await _run(pg_pool, listing_id, property_id, state)

        current = await _contacts(pg_pool, property_id)
        assert current["phone"] == ("(313) 555-0142", "listing")
    finally:
        await _cleanup(pg_pool, hunt_id, property_id)


async def test_aggregator_contact_url_is_rejected_by_the_domain_guard(
    pg_pool: asyncpg.Pool,
) -> None:
    """An aggregator's 'contact us' page is a lead form for the aggregator."""
    hunt_id, property_id, listing_id = await _seed(pg_pool)
    try:
        state = _state(
            url=f"https://aggregator.test/{uuid4()}",
            property_contact=PropertyContactIn(contact_url="https://aggregator.test/contact"),
        )
        await _run(pg_pool, listing_id, property_id, state)

        assert "contact_url" not in await _contacts(pg_pool, property_id)
    finally:
        await _cleanup(pg_pool, hunt_id, property_id)


async def test_reingest_refreshes_instead_of_appending_duplicates(pg_pool: asyncpg.Pool) -> None:
    """Append-only must not mean unbounded: the same page seen twice is one row."""
    hunt_id, property_id, listing_id = await _seed(pg_pool)
    try:
        url = f"https://aggregator.test/{uuid4()}"
        for _ in range(2):
            await _run(
                pg_pool,
                listing_id,
                property_id,
                _state(url=url, property_contact=PropertyContactIn(phone="313-555-0142")),
            )

        total = await pg_pool.fetchval(
            "select count(*) from property_contacts where property_id = $1", property_id
        )
        assert total == 1
    finally:
        await _cleanup(pg_pool, hunt_id, property_id)


async def test_no_contact_found_writes_nothing(pg_pool: asyncpg.Pool) -> None:
    """The designed give-up state: no rows, so the drawer renders no Contact row."""
    hunt_id, property_id, listing_id = await _seed(pg_pool)
    try:
        await _run(pg_pool, listing_id, property_id, _state(url=f"https://x.test/{uuid4()}"))
        assert await _contacts(pg_pool, property_id) == {}
    finally:
        await _cleanup(pg_pool, hunt_id, property_id)
