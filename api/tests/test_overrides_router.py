"""P1-8 overrides router tests."""

from __future__ import annotations

from uuid import uuid4

import pytest
from api_helpers import FAKE_USER
from httpx import AsyncClient


async def _seed_listing(db_pool):  # type: ignore[no-untyped-def]
    hunt_id, listing_id, property_id = uuid4(), uuid4(), uuid4()
    await db_pool.execute(
        "insert into hunts (id, name, owner_id) values ($1, 'O', $2)",
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
async def test_create_override_enqueues_rescore(client: AsyncClient, db_pool) -> None:
    hunt_id, listing_id, property_id = await _seed_listing(db_pool)
    try:
        resp = await client.post(
            f"/v1/listings/{listing_id}/overrides",
            json={"criterion_key": "beds", "value": 2, "note": "manual"},
        )
        assert resp.status_code == 201
        assert resp.json()["user_id"] == FAKE_USER.id
        count = await db_pool.fetchval(
            "select count(*) from overrides where hunt_listing_id = $1", listing_id
        )
        assert count == 1
        rescore = await db_pool.fetchval(
            "select count(*) from jobs where type = 'rescore' and payload->>'hunt_id' = $1",
            str(hunt_id),
        )
        assert rescore == 1
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)
        await db_pool.execute("delete from properties where id = $1", property_id)


@pytest.mark.asyncio
async def test_create_exact_floor_plan_override(client: AsyncClient, db_pool) -> None:
    hunt_id, listing_id, property_id = await _seed_listing(db_pool)
    source_id = await db_pool.fetchval(
        "insert into property_sources (property_id, url, site_domain) "
        "values ($1, $2, 'example.com') returning id",
        property_id,
        f"https://example.com/{uuid4()}",
    )
    floor_plan_id = await db_pool.fetchval(
        "insert into floor_plans (property_id, source_id, plan_name, beds, baths) "
        "values ($1, $2, 'A1', 1, 1) returning id",
        property_id,
        source_id,
    )
    try:
        resp = await client.post(
            f"/v1/listings/{listing_id}/overrides",
            json={
                "criterion_key": "dishwasher",
                "value": True,
                "target_scope": "floor_plan",
                "floor_plan_id": str(floor_plan_id),
                "applicability": "specific_floor_plans",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["floor_plan_id"] == str(floor_plan_id)
        assert resp.json()["target_scope"] == "floor_plan"
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)
        await db_pool.execute("delete from properties where id = $1", property_id)


@pytest.mark.asyncio
async def test_rejects_floor_plan_from_another_property(client: AsyncClient, db_pool) -> None:
    hunt_id, listing_id, property_id = await _seed_listing(db_pool)
    other_property_id = await db_pool.fetchval(
        "insert into properties (name, canonical_address) values ('Other', 'b') returning id"
    )
    source_id = await db_pool.fetchval(
        "insert into property_sources (property_id, url, site_domain) "
        "values ($1, $2, 'example.com') returning id",
        other_property_id,
        f"https://example.com/{uuid4()}",
    )
    foreign_plan_id = await db_pool.fetchval(
        "insert into floor_plans (property_id, source_id, plan_name, beds, baths) "
        "values ($1, $2, 'B2', 2, 2) returning id",
        other_property_id,
        source_id,
    )
    try:
        resp = await client.post(
            f"/v1/listings/{listing_id}/overrides",
            json={
                "criterion_key": "dishwasher",
                "value": True,
                "target_scope": "floor_plan",
                "floor_plan_id": str(foreign_plan_id),
                "applicability": "specific_floor_plans",
            },
        )
        assert resp.status_code == 422
        assert resp.json()["code"] == "invalid_override_target"
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)
        await db_pool.execute(
            "delete from properties where id = any($1::uuid[])",
            [property_id, other_property_id],
        )
