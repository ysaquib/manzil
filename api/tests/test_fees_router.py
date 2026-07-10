"""P1-8 fees router tests."""

from __future__ import annotations

from uuid import uuid4

import pytest
from api_helpers import FAKE_USER
from httpx import AsyncClient


async def _seed_listing(db_pool):  # type: ignore[no-untyped-def]
    hunt_id, listing_id, property_id = uuid4(), uuid4(), uuid4()
    await db_pool.execute(
        "insert into hunts (id, name, owner_id) values ($1, 'F', $2)",
        hunt_id,
        FAKE_USER.id,
    )
    await db_pool.execute(
        "insert into properties (id, name, canonical_address) values ($1, 'P', 'a')",
        property_id,
    )
    await db_pool.execute(
        """
        insert into hunt_listings (id, hunt_id, property_id, added_by)
        values ($1, $2, $3, $4)
        """,
        listing_id,
        hunt_id,
        property_id,
        FAKE_USER.id,
    )
    return hunt_id, listing_id


@pytest.mark.asyncio
async def test_upsert_fee_enqueues_rescore(client: AsyncClient, db_pool) -> None:
    hunt_id, listing_id = await _seed_listing(db_pool)
    try:
        resp = await client.put(
            f"/v1/listings/{listing_id}/fees/parking",
            json={"amount": 50.0, "value_state": "manual"},
        )
        assert resp.status_code == 200
        assert resp.json()["fee_slot"] == "parking"
        rescore = await db_pool.fetchval(
            "select count(*) from jobs where type = 'rescore' and payload->>'hunt_id' = $1",
            str(hunt_id),
        )
        assert rescore == 1
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)


@pytest.mark.asyncio
async def test_upsert_fee_bumps_updated_at(client: AsyncClient, db_pool) -> None:
    hunt_id, listing_id = await _seed_listing(db_pool)
    try:
        first = await client.put(
            f"/v1/listings/{listing_id}/fees/parking",
            json={"amount": 50.0, "value_state": "manual"},
        )
        assert first.status_code == 200
        first_updated = await db_pool.fetchval(
            "select updated_at from fee_checklist"
            " where hunt_listing_id = $1 and fee_slot = 'parking'",
            listing_id,
        )

        # Re-entering the same (hunt_listing_id, fee_slot) must bump updated_at,
        # not freeze it at the INSERT default.
        second = await client.put(
            f"/v1/listings/{listing_id}/fees/parking",
            json={"amount": 75.0, "value_state": "manual"},
        )
        assert second.status_code == 200
        second_updated = await db_pool.fetchval(
            "select updated_at from fee_checklist"
            " where hunt_listing_id = $1 and fee_slot = 'parking'",
            listing_id,
        )
        assert second_updated > first_updated
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)
