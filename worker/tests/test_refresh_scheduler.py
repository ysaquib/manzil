"""P3-12 TTL scheduler coverage."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import asyncpg
from manzil_shared.models import JobType
from manzil_worker.queue import (
    _refresh_failure_backoff_active,
    _successful_refresh_fields,
    refresh_ttl_tick,
)
from manzil_worker.state import RunState


def test_partial_image_refresh_advances_text_but_not_image_freshness() -> None:
    state = RunState(job_id=uuid4(), job_type=JobType.REFRESH, url="https://example.test")
    assert not state.image_fetch_completed
    assert _successful_refresh_fields(state, ["images"]) == [
        "pricing",
        "listing_details",
    ]

    state.image_fetch_completed = True
    assert _successful_refresh_fields(state, ["images"]) == ["images"]


def test_cap_saturated_partial_counts_as_image_freshness() -> None:
    state = RunState(job_id=uuid4(), job_type=JobType.REFRESH, url="https://example.test")
    state.image_fetch_completed = True
    state.image_fetch_strict_complete = False
    assert _successful_refresh_fields(state, ["images"]) == ["images"]


def test_failed_refresh_backoff_is_exponential_and_capped() -> None:
    now = datetime.now(UTC)

    assert _refresh_failure_backoff_active(
        {"failure_count": 1, "last_failed_at": now - timedelta(minutes=59)}, now=now
    )
    assert not _refresh_failure_backoff_active(
        {"failure_count": 1, "last_failed_at": now - timedelta(minutes=61)}, now=now
    )
    assert _refresh_failure_backoff_active(
        {"failure_count": 2, "last_failed_at": now - timedelta(minutes=61)}, now=now
    )
    assert not _refresh_failure_backoff_active(
        {"failure_count": 2, "last_failed_at": now - timedelta(minutes=121)}, now=now
    )
    assert _refresh_failure_backoff_active(
        {"failure_count": 99, "last_failed_at": now - timedelta(hours=23)}, now=now
    )
    assert not _refresh_failure_backoff_active(
        {"failure_count": 99, "last_failed_at": now - timedelta(hours=25)}, now=now
    )


async def test_refresh_ttl_tick_skips_images_when_cap_saturated_ingest_marked_fresh(
    pg_pool: asyncpg.Pool,
) -> None:
    hunt_id, property_id, listing_id = uuid4(), uuid4(), uuid4()
    owner_id, source_id, ingest_job_id = uuid4(), uuid4(), uuid4()
    await pg_pool.execute(
        "insert into hunts (id, name, owner_id) values ($1, 'Cap saturated', $2)",
        hunt_id,
        owner_id,
    )
    await pg_pool.execute(
        "insert into rubric_criteria (hunt_id, catalog_key) values ($1, 'kitchen_quality')",
        hunt_id,
    )
    await pg_pool.execute(
        "insert into properties (id, name, canonical_address) values ($1, 'Images', '3 Clock St')",
        property_id,
    )
    await pg_pool.execute(
        """
        insert into property_sources (id, property_id, url, site_domain, last_success_at)
        values ($1, $2, 'https://cap.example/listing', 'cap.example', now())
        """,
        source_id,
        property_id,
    )
    await pg_pool.execute(
        """
        insert into hunt_listings (id, hunt_id, property_id, added_by, submitted_source_id)
        values ($1, $2, $3, $4, $5)
        """,
        listing_id,
        hunt_id,
        property_id,
        owner_id,
        source_id,
    )
    run_state = RunState(
        job_id=ingest_job_id,
        job_type=JobType.INGEST,
        url="https://cap.example/listing",
    )
    run_state.image_fetch_completed = True
    run_state.image_fetch_strict_complete = False
    await pg_pool.execute(
        """
        insert into jobs (
            id, hunt_id, hunt_listing_id, type, state, payload, plan,
            created_at, started_at, finished_at
        ) values (
            $1, $2, $3, 'ingest', 'done', $4::jsonb,
            '{"stages":["IMAGE_FETCH"]}'::jsonb,
            now() - interval '70 minutes', now() - interval '69 minutes',
            now() - interval '181 minutes'
        )
        """,
        ingest_job_id,
        hunt_id,
        listing_id,
        json.dumps(
            {
                "url": "https://cap.example/listing",
                "run_state": run_state.model_dump(mode="json"),
            }
        ),
    )
    now = datetime.now(UTC)
    await pg_pool.executemany(
        """
        insert into hunt_listing_refresh_status
            (hunt_listing_id, refresh_class, last_success_at, producer_job_id)
        values ($1, $2, $3, $4)
        """,
        [
            (listing_id, "pricing", now, ingest_job_id),
            (listing_id, "listing_details", now, ingest_job_id),
            (listing_id, "images", now, ingest_job_id),
        ],
    )
    try:
        await refresh_ttl_tick(pg_pool)
        refresh_count = await pg_pool.fetchval(
            "select count(*) from jobs where hunt_listing_id = $1 and type = 'refresh'",
            listing_id,
        )
        assert refresh_count == 0
        images_marker = await pg_pool.fetchval(
            """
            select last_success_at from hunt_listing_refresh_status
            where hunt_listing_id = $1 and refresh_class = 'images'
            """,
            listing_id,
        )
        assert images_marker is not None
    finally:
        await pg_pool.execute("delete from hunts where id = $1", hunt_id)
        await pg_pool.execute("delete from properties where id = $1", property_id)


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


async def test_refresh_ttl_tick_backs_off_after_partial_image_ingest(
    pg_pool: asyncpg.Pool,
) -> None:
    hunt_id, property_id, listing_id = uuid4(), uuid4(), uuid4()
    owner_id, source_id, ingest_job_id = uuid4(), uuid4(), uuid4()
    await pg_pool.execute(
        "insert into hunts (id, name, owner_id) values ($1, 'Image retry', $2)",
        hunt_id,
        owner_id,
    )
    await pg_pool.execute(
        "insert into rubric_criteria (hunt_id, catalog_key) values ($1, 'kitchen_quality')",
        hunt_id,
    )
    await pg_pool.execute(
        "insert into properties (id, name, canonical_address) values ($1, 'Images', '2 Clock St')",
        property_id,
    )
    await pg_pool.execute(
        """
        insert into property_sources (id, property_id, url, site_domain, last_success_at)
        values ($1, $2, 'https://images.example/listing', 'images.example', now())
        """,
        source_id,
        property_id,
    )
    await pg_pool.execute(
        """
        insert into hunt_listings (id, hunt_id, property_id, added_by, submitted_source_id)
        values ($1, $2, $3, $4, $5)
        """,
        listing_id,
        hunt_id,
        property_id,
        owner_id,
        source_id,
    )
    await pg_pool.execute(
        """
        insert into jobs (
            id, hunt_id, hunt_listing_id, type, state, payload, plan,
            created_at, started_at, finished_at
        ) values (
            $1, $2, $3, 'ingest', 'done', $4::jsonb,
            '{"stages":["IMAGE_FETCH"]}'::jsonb,
            now() - interval '10 minutes', now() - interval '9 minutes', now()
        )
        """,
        ingest_job_id,
        hunt_id,
        listing_id,
        json.dumps(
            {
                "url": "https://images.example/listing",
                "run_state": RunState(
                    job_id=ingest_job_id,
                    job_type=JobType.INGEST,
                    url="https://images.example/listing",
                ).model_dump(mode="json"),
            }
        ),
    )
    now = datetime.now(UTC)
    await pg_pool.executemany(
        """
        insert into hunt_listing_refresh_status
            (hunt_listing_id, refresh_class, last_success_at)
        values ($1, $2, $3)
        """,
        [
            (listing_id, "pricing", now),
            (listing_id, "listing_details", now),
        ],
    )
    try:
        await refresh_ttl_tick(pg_pool)
        count = await pg_pool.fetchval(
            "select count(*) from jobs where hunt_listing_id = $1 and type = 'refresh'",
            listing_id,
        )
        assert count == 0

        await pg_pool.execute(
            "update jobs set finished_at = now() - interval '181 minutes' where id = $1",
            ingest_job_id,
        )
        await refresh_ttl_tick(pg_pool)
        row = await pg_pool.fetchrow(
            "select payload from jobs where hunt_listing_id = $1 and type = 'refresh'",
            listing_id,
        )
        assert row is not None
        payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
        assert payload["fields"] == ["images"]
        assert payload["trigger"] == "ttl:images"
    finally:
        await pg_pool.execute("delete from hunts where id = $1", hunt_id)
        await pg_pool.execute("delete from properties where id = $1", property_id)


async def test_refresh_ttl_tick_excludes_seed_sources_and_backs_off_failed_classes(
    pg_pool: asyncpg.Pool,
) -> None:
    hunt_id, owner_id = uuid4(), uuid4()
    seed_property_id, real_property_id = uuid4(), uuid4()
    seed_listing_id, real_listing_id = uuid4(), uuid4()
    seed_source_id, real_source_id, failed_job_id = uuid4(), uuid4(), uuid4()
    seed_domain = f"fixture-{seed_source_id}.seed.example"
    await pg_pool.execute(
        "insert into hunts (id, name, owner_id) values ($1, 'Scheduler guards', $2)",
        hunt_id,
        owner_id,
    )
    await pg_pool.executemany(
        "insert into properties (id, name, canonical_address) values ($1, $2, $3)",
        [
            (seed_property_id, "Fixture", "1 Seed St"),
            (real_property_id, "Real", "2 Real St"),
        ],
    )
    await pg_pool.executemany(
        """
        insert into property_sources
            (id, property_id, url, site_domain, last_success_at)
        values ($1, $2, $3, $4, now())
        """,
        [
            (
                seed_source_id,
                seed_property_id,
                f"https://{seed_domain}/apartments",
                seed_domain,
            ),
            (
                real_source_id,
                real_property_id,
                "https://real.example.test/apartments",
                "real.example.test",
            ),
        ],
    )
    await pg_pool.executemany(
        """
        insert into hunt_listings
            (id, hunt_id, property_id, added_by, submitted_source_id)
        values ($1, $2, $3, $4, $5)
        """,
        [
            (seed_listing_id, hunt_id, seed_property_id, owner_id, seed_source_id),
            (real_listing_id, hunt_id, real_property_id, owner_id, real_source_id),
        ],
    )
    stale = datetime.now(UTC) - timedelta(hours=25)
    fresh = datetime.now(UTC)
    await pg_pool.executemany(
        """
        insert into hunt_listing_refresh_status
            (hunt_listing_id, refresh_class, last_success_at)
        values ($1, $2, $3)
        """,
        [
            (seed_listing_id, "pricing", stale),
            (seed_listing_id, "listing_details", fresh),
            (real_listing_id, "pricing", stale),
            (real_listing_id, "listing_details", fresh),
        ],
    )
    await pg_pool.execute(
        """
        insert into jobs (
            id, hunt_id, hunt_listing_id, type, state, payload, finished_at
        ) values (
            $1, $2, $3, 'refresh', 'failed',
            '{"fields":["pricing"],"scope":"classes"}'::jsonb,
            now()
        )
        """,
        failed_job_id,
        hunt_id,
        real_listing_id,
    )
    try:
        await refresh_ttl_tick(pg_pool)
        assert (
            await pg_pool.fetchval(
                "select count(*) from jobs where type = 'refresh' and state = 'queued' "
                "and hunt_id = $1",
                hunt_id,
            )
            == 0
        )

        await pg_pool.execute(
            "update jobs set finished_at = now() - interval '61 minutes' where id = $1",
            failed_job_id,
        )
        await refresh_ttl_tick(pg_pool)
        queued = await pg_pool.fetchrow(
            """
            select hunt_listing_id, payload from jobs
            where hunt_id = $1 and type = 'refresh' and state = 'queued'
            """,
            hunt_id,
        )
        assert queued is not None
        assert queued["hunt_listing_id"] == real_listing_id
        payload = (
            json.loads(queued["payload"])
            if isinstance(queued["payload"], str)
            else queued["payload"]
        )
        assert payload["fields"] == ["pricing"]
    finally:
        await pg_pool.execute("delete from hunts where id = $1", hunt_id)
        await pg_pool.execute(
            "delete from properties where id = any($1::uuid[])",
            [seed_property_id, real_property_id],
        )
