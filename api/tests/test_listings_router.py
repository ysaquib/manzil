"""P1-7 listings router tests."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from api_helpers import FAKE_USER
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_listing_inserts_property_and_ingest_job(client: AsyncClient, db_pool) -> None:
    hunt_id = uuid4()
    await db_pool.execute(
        """
        insert into hunts (id, name, owner_id, settings)
        values ($1, 'L', $2, $3::jsonb)
        """,
        hunt_id,
        FAKE_USER.id,
        json.dumps({"default_source_policy": "tiers_1_2_3"}),
    )
    try:
        url = "https://maple-court.seed.example/floorplans"
        resp = await client.post(f"/v1/hunts/{hunt_id}/listings", json={"url": url})
        assert resp.status_code == 201
        listing_id = resp.json()["id"]
        job = await db_pool.fetchrow(
            "select type, state, payload from jobs where hunt_listing_id = $1",
            listing_id,
        )
        assert job is not None
        assert job["type"] == "ingest"
        assert job["state"] == "queued"
        payload = json.loads(job["payload"]) if isinstance(job["payload"], str) else job["payload"]
        assert payload["url"] == url
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)


@pytest.mark.asyncio
async def test_delete_listing_soft_archives(client: AsyncClient, db_pool) -> None:
    hunt_id, listing_id, property_id = uuid4(), uuid4(), uuid4()
    await db_pool.execute(
        "insert into hunts (id, name, owner_id) values ($1, 'L', $2)",
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
    job_id = await db_pool.fetchval(
        """
        insert into jobs (hunt_id, hunt_listing_id, type, state, payload)
        values ($1, $2, 'ingest', 'done', '{}'::jsonb) returning id
        """,
        hunt_id,
        listing_id,
    )
    try:
        resp = await client.delete(f"/v1/listings/{listing_id}")
        assert resp.status_code == 204
        status = await db_pool.fetchval(
            "select status from hunt_listings where id = $1", listing_id
        )
        assert status == "archived"
        job_exists = await db_pool.fetchval("select id from jobs where id = $1", job_id)
        assert job_exists is not None
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)
