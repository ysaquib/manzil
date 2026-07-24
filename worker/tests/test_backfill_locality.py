"""Backfill locality on existing Properties."""

from __future__ import annotations

from uuid import uuid4

import asyncpg
from manzil_worker.ops.backfill_locality import backfill_locality


async def _seed(pool: asyncpg.Pool) -> asyncpg.Record:
    property_id = uuid4()
    await pool.execute(
        """
        insert into properties (id, name, canonical_address)
        values ($1, 'P', '120 Main St, Detroit, MI 48201')
        """,
        property_id,
    )
    return await pool.fetchrow("select * from properties where id = $1", property_id)


async def test_backfill_locality_persists_with_coalesce(pg_pool: asyncpg.Pool) -> None:
    row = await _seed(pg_pool)
    try:

        async def fake_geocode(address: str):  # type: ignore[no-untyped-def]
            assert address == row["canonical_address"]
            return {
                "place_id": "PLACE_X",
                "lat": 42.3,
                "lng": -83.4,
                "city": "Detroit",
                "state": "MI",
                "county": "Wayne County",
            }

        result = await backfill_locality(pg_pool, geocode_call=fake_geocode)
        assert result == type(result)(attempted=1, updated=1, failed=0)
        updated = await pg_pool.fetchrow("select * from properties where id = $1", row["id"])
        assert updated["city"] == "Detroit"
        assert updated["state"] == "MI"
        assert updated["county"] == "Wayne County"
        assert updated["place_id"] == "PLACE_X"
    finally:
        await pg_pool.execute("delete from properties where id = $1", row["id"])


async def test_backfill_locality_is_idempotent_and_skips_failures(pg_pool: asyncpg.Pool) -> None:
    good_id, bad_id = uuid4(), uuid4()
    await pg_pool.execute(
        """
        insert into properties (id, name, canonical_address, city)
        values ($1, 'Good', '120 Main St, Detroit, MI 48201', 'OldCity'),
               ($2, 'Bad', '', null)
        """,
        good_id,
        bad_id,
    )
    try:

        async def fake_geocode(address: str):  # type: ignore[no-untyped-def]
            if address is None:
                raise AssertionError("unexpected")
            return {
                "place_id": "PLACE_X",
                "lat": 42.3,
                "lng": -83.4,
                "city": "Detroit",
                "state": "MI",
                "county": "Wayne County",
            }

        first = await backfill_locality(pg_pool, geocode_call=fake_geocode)
        assert first.attempted == 2 and first.updated == 1 and first.failed == 1
        second = await backfill_locality(pg_pool, geocode_call=fake_geocode)
        assert second.attempted == 1 and second.updated == 0 and second.failed == 1
        row = await pg_pool.fetchrow("select city, state from properties where id = $1", good_id)
        assert row["city"] == "OldCity"
        assert row["state"] == "MI"
    finally:
        await pg_pool.execute(
            "delete from properties where id = any($1::uuid[])", [good_id, bad_id]
        )
