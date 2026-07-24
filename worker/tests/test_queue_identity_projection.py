"""Property-identity projection (DESIGN §20 2026-07-10): EXTRACT's non-catalog
identity block updates the global `properties` row with non-null-wins semantics
(extracted value overwrites, null leaves the placeholder). Skips cleanly without
Postgres like its queue-test neighbors (test_queue_projection_atomic.py)."""

from __future__ import annotations

from uuid import uuid4

import asyncpg
from manzil_shared.models import FetchOutcome, JobType
from manzil_worker.queue import _persist_ingest_results
from manzil_worker.state import GeocodeIn, PropertyIdentityIn, RunState, SourceState


async def _seed(pool: asyncpg.Pool, *, name: str, address: str) -> tuple:
    hunt_id = uuid4()
    property_id = uuid4()
    listing_id = uuid4()
    await pool.execute(
        "insert into hunts (id, name, owner_id) values ($1, 'test', $2)", hunt_id, uuid4()
    )
    await pool.execute(
        "insert into properties (id, name, canonical_address) values ($1, $2, $3)",
        property_id,
        name,
        address,
    )
    await pool.execute(
        "insert into hunt_listings (id, hunt_id, property_id, added_by) values ($1, $2, $3, $4)",
        listing_id,
        hunt_id,
        property_id,
        uuid4(),
    )
    return hunt_id, property_id, listing_id


async def _cleanup(pool: asyncpg.Pool, hunt_id, property_id) -> None:
    await pool.execute("delete from hunts where id = $1", hunt_id)  # cascades hunt_listings
    await pool.execute("delete from properties where id = $1", property_id)  # cascades sources


def _state(
    url: str,
    identity: PropertyIdentityIn | None,
    *,
    cleaned_text: str = "x",
    cleaned_hash: str = "abc123",
) -> RunState:
    state = RunState(job_id=uuid4(), job_type=JobType.INGEST, url=url)
    state.sources = [
        SourceState(
            url=url,
            tier_used=1,
            outcome=FetchOutcome.SUCCESS,
            cleaned_text=cleaned_text,
            cleaned_hash=cleaned_hash,
        )
    ]
    state.property_identity = identity
    return state


async def _run_persist(pool: asyncpg.Pool, listing_id, property_id, state: RunState) -> None:
    async with pool.acquire() as conn, conn.transaction():
        await _persist_ingest_results(
            conn,
            hunt_listing_id=listing_id,
            property_id=property_id,
            rubric_version=1,
            state=state,
        )


async def test_identity_overwrites_placeholder_row(pg_pool: asyncpg.Pool) -> None:
    hunt_id, property_id, listing_id = await _seed(pg_pool, name="listing-4", address="listing-4")
    try:
        state = _state(
            "https://x.test/identity-full",
            PropertyIdentityIn(
                name="Maple Court Apartments",
                address="120 Maple Court Dr, Detroit, MI 48187",
            ),
        )
        await _run_persist(pg_pool, listing_id, property_id, state)

        row = await pg_pool.fetchrow(
            "select name, canonical_address, official_url from properties where id = $1",
            property_id,
        )
        assert row["name"] == "Maple Court Apartments"
        assert row["canonical_address"] == "120 Maple Court Dr, Detroit, MI 48187"
        assert row["official_url"] is None
    finally:
        await _cleanup(pg_pool, hunt_id, property_id)


async def test_none_identity_leaves_row_untouched(pg_pool: asyncpg.Pool) -> None:
    hunt_id, property_id, listing_id = await _seed(pg_pool, name="listing-4", address="listing-4")
    try:
        state = _state("https://x.test/identity-none", None)
        await _run_persist(pg_pool, listing_id, property_id, state)

        row = await pg_pool.fetchrow(
            "select name, canonical_address from properties where id = $1", property_id
        )
        assert row["name"] == "listing-4"
        assert row["canonical_address"] == "listing-4"
    finally:
        await _cleanup(pg_pool, hunt_id, property_id)


async def test_cleaned_text_persists_and_updates_on_reingest(pg_pool: asyncpg.Pool) -> None:
    """The property_sources row keeps the exact cleaned text the model saw
    (migration 0007 debugging artifact), and a re-ingest of the same url
    overwrites it on conflict — provenance tracks the latest fetch."""
    hunt_id, property_id, listing_id = await _seed(pg_pool, name="listing-4", address="listing-4")
    url = "https://x.test/cleaned-text"
    try:
        first = _state(url, None, cleaned_text="first fetch body", cleaned_hash="hash-1")
        await _run_persist(pg_pool, listing_id, property_id, first)
        text, digest = await pg_pool.fetchrow(
            "select cleaned_text, cleaned_text_hash from property_sources where url = $1", url
        )
        assert text == "first fetch body"
        assert digest == "hash-1"

        second = _state(url, None, cleaned_text="second fetch body", cleaned_hash="hash-2")
        await _run_persist(pg_pool, listing_id, property_id, second)
        text, digest = await pg_pool.fetchrow(
            "select cleaned_text, cleaned_text_hash from property_sources where url = $1", url
        )
        assert text == "second fetch body"
        assert digest == "hash-2"
    finally:
        await _cleanup(pg_pool, hunt_id, property_id)


async def test_geocode_locality_coalesces_without_overwriting(pg_pool: asyncpg.Pool) -> None:
    hunt_id, property_id, listing_id = await _seed(
        pg_pool, name="listing-4", address="listing-4"
    )
    try:
        state = _state("https://x.test/geocode-locality", None)
        state.geocode = GeocodeIn(
            place_id="PLACE_1",
            lat=42.3,
            lng=-83.4,
            city="Canton",
            state="MI",
            county="Wayne County",
        )
        await _run_persist(pg_pool, listing_id, property_id, state)
        row = await pg_pool.fetchrow(
            "select city, state, county, place_id from properties where id = $1",
            property_id,
        )
        assert row["city"] == "Canton"
        assert row["state"] == "MI"
        assert row["county"] == "Wayne County"
        assert row["place_id"] == "PLACE_1"

        state.geocode = GeocodeIn(
            place_id="PLACE_2",
            lat=43.0,
            lng=-84.0,
            city="Detroit",
            state="MI",
            county="Wayne County",
        )
        await _run_persist(pg_pool, listing_id, property_id, state)
        row = await pg_pool.fetchrow(
            "select city, state, county, place_id from properties where id = $1",
            property_id,
        )
        assert row["city"] == "Canton"
        assert row["state"] == "MI"
        assert row["place_id"] == "PLACE_1"
    finally:
        await _cleanup(pg_pool, hunt_id, property_id)


async def test_null_address_updates_only_name(pg_pool: asyncpg.Pool) -> None:
    """Non-null-wins: a name with no address overwrites the name and leaves the
    existing canonical_address placeholder in place."""
    hunt_id, property_id, listing_id = await _seed(pg_pool, name="listing-4", address="listing-4")
    try:
        state = _state(
            "https://x.test/identity-name-only",
            PropertyIdentityIn(name="Maple Court Apartments", address=None),
        )
        await _run_persist(pg_pool, listing_id, property_id, state)

        row = await pg_pool.fetchrow(
            "select name, canonical_address from properties where id = $1", property_id
        )
        assert row["name"] == "Maple Court Apartments"
        assert row["canonical_address"] == "listing-4"
    finally:
        await _cleanup(pg_pool, hunt_id, property_id)
