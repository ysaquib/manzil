"""P3-12 TTL scheduler coverage."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import asyncpg
from manzil_worker.queue import refresh_ttl_tick


async def test_refresh_ttl_tick_uses_24_hour_pricing_ttl_and_coalesces(
    pg_pool: asyncpg.Pool,
) -> None:
    hunt_id, property_id, listing_id = uuid4(), uuid4(), uuid4()
    owner_id, source_id = uuid4(), uuid4()
    await pg_pool.execute(
        "insert into hunts (id, name, owner_id) values ($1, 'Refresh TTL', $2)",
        hunt_id,
        owner_id,
    )
    await pg_pool.execute(
        """
        insert into properties (id, name, canonical_address)
        values ($1, 'TTL Property', '1 Clock St')
        """,
        property_id,
    )
    await pg_pool.execute(
        """
        insert into property_sources
            (id, property_id, url, site_domain, last_success_at)
        values ($1, $2, 'https://ttl.example/listing', 'ttl.example', now())
        """,
        source_id,
        property_id,
    )
    await pg_pool.execute(
        """
        insert into hunt_listings
            (id, hunt_id, property_id, added_by, submitted_source_id)
        values ($1, $2, $3, $4, $5)
        """,
        listing_id,
        hunt_id,
        property_id,
        owner_id,
        source_id,
    )
    now = datetime.now(UTC)
    await pg_pool.executemany(
        """
        insert into hunt_listing_refresh_status
            (hunt_listing_id, refresh_class, last_success_at)
        values ($1, $2, $3)
        """,
        [
            (listing_id, "pricing", now - timedelta(hours=25)),
            (listing_id, "listing_details", now - timedelta(days=1)),
        ],
    )
    try:
        await refresh_ttl_tick(pg_pool)
        row = await pg_pool.fetchrow(
            """
            select payload from jobs
            where hunt_listing_id = $1 and type = 'refresh'
            """,
            listing_id,
        )
        assert row is not None
        payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
        assert payload["fields"] == ["pricing"]
        assert payload["trigger"] == "ttl:pricing"

        await refresh_ttl_tick(pg_pool)
        count = await pg_pool.fetchval(
            """
            select count(*) from jobs
            where hunt_listing_id = $1 and type = 'refresh'
            """,
            listing_id,
        )
        assert count == 1
    finally:
        await pg_pool.execute("delete from hunts where id = $1", hunt_id)
        await pg_pool.execute("delete from properties where id = $1", property_id)
