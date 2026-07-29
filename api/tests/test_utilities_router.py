"""Per-utility inclusion/cost override route (§9.5)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from api_helpers import FAKE_USER
from httpx import AsyncClient


async def _seed_listing(db_pool):  # type: ignore[no-untyped-def]
    hunt_id, listing_id, property_id = uuid4(), uuid4(), uuid4()
    await db_pool.execute(
        "insert into hunts (id, name, owner_id) values ($1, 'Utilities', $2)",
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
    return hunt_id, listing_id, property_id


@pytest.mark.asyncio
async def test_utility_override_and_revert_are_append_only(client: AsyncClient, db_pool) -> None:
    hunt_id, listing_id, property_id = await _seed_listing(db_pool)
    try:
        override = await client.put(
            f"/v1/listings/{listing_id}/utilities/electric",
            json={"included": False, "monthly_amount": 92.5},
        )
        assert override.status_code == 200
        assert override.json()["included"] is False
        assert override.json()["monthly_amount"] == 92.5

        revert = await client.put(
            f"/v1/listings/{listing_id}/utilities/electric",
            json={"included": None, "monthly_amount": None},
        )
        assert revert.status_code == 200
        assert revert.json()["included"] is None
        assert revert.json()["monthly_amount"] is None

        rows = await db_pool.fetch(
            """
            select included, monthly_amount from utility_overrides
            where hunt_listing_id = $1 order by created_at, id
            """,
            listing_id,
        )
        assert [(row["included"], row["monthly_amount"]) for row in rows] == [
            (False, 92.5),
            (None, None),
        ]
        current = await db_pool.fetchrow(
            """
            select included, monthly_amount from current_utility_overrides
            where hunt_listing_id = $1 and utility = 'electric'
            """,
            listing_id,
        )
        assert current["included"] is None
        assert current["monthly_amount"] is None
        assert (
            await db_pool.fetchval(
                "select count(*) from jobs where type = 'rescore' and hunt_id = $1",
                hunt_id,
            )
            == 2
        )
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)
        await db_pool.execute("delete from properties where id = $1", property_id)


@pytest.mark.asyncio
async def test_utility_route_rejects_unknown_utility(client: AsyncClient, db_pool) -> None:
    hunt_id, listing_id, property_id = await _seed_listing(db_pool)
    try:
        response = await client.put(
            f"/v1/listings/{listing_id}/utilities/steam",
            json={"included": True, "monthly_amount": None},
        )
        assert response.status_code == 422
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)
        await db_pool.execute("delete from properties where id = $1", property_id)
