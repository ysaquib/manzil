"""P3-12 TTL scheduler coverage."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import asyncpg
from manzil_shared.config import (
    IMAGE_REFRESH_STALL_COOLDOWN_HOURS,
    IMAGE_REFRESH_STALL_MAX_ATTEMPTS,
    REFRESH_TTL_HOURS,
)
from manzil_shared.models import JobType
from manzil_worker.queue import (
    _clear_refresh_stall,
    _image_stall_next_eligible,
    _reconcile_refresh_classes,
    _record_refresh_stall,
    _stall_backoff_hours,
    _stall_outcome_for_class,
    _successful_refresh_fields,
    refresh_ttl_tick,
)
from manzil_worker.state import PropertyImageIn, RunState, StageWarning


def test_partial_image_refresh_does_not_advance_unrequested_class_freshness() -> None:
    state = RunState(job_id=uuid4(), job_type=JobType.REFRESH, url="https://example.test")
    assert not state.image_fetch_completed
    assert _successful_refresh_fields(state, ["images"]) == []

    state.image_fetch_completed = True
    assert _successful_refresh_fields(state, ["images"]) == ["images"]


def test_cap_saturated_partial_counts_as_image_freshness() -> None:
    state = RunState(job_id=uuid4(), job_type=JobType.REFRESH, url="https://example.test")
    state.image_fetch_completed = True
    state.image_fetch_strict_complete = False
    assert _successful_refresh_fields(state, ["images"]) == ["images"]


def test_stall_backoff_hours_is_exponential_and_capped_at_72() -> None:
    assert _stall_backoff_hours(1) == 3
    assert _stall_backoff_hours(2) == 6
    assert _stall_backoff_hours(3) == 12
    assert _stall_backoff_hours(4) == 24
    assert _stall_backoff_hours(5) == 48
    assert _stall_backoff_hours(6) == 72
    assert _stall_backoff_hours(7) == 72
    assert _stall_backoff_hours(99) == 72


def test_image_stall_next_eligible_flat_cooldown_then_ttl_fallback() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    for attempt in range(1, IMAGE_REFRESH_STALL_MAX_ATTEMPTS):
        assert _image_stall_next_eligible(attempt, now) == now + timedelta(
            hours=IMAGE_REFRESH_STALL_COOLDOWN_HOURS
        )
    # The Nth consecutive stall (and every one after) falls back to the
    # ordinary 60-day images TTL instead of another short-cooldown retry.
    assert _image_stall_next_eligible(IMAGE_REFRESH_STALL_MAX_ATTEMPTS, now) == now + timedelta(
        hours=REFRESH_TTL_HOURS["images"]
    )
    assert _image_stall_next_eligible(IMAGE_REFRESH_STALL_MAX_ATTEMPTS + 5, now) == now + timedelta(
        hours=REFRESH_TTL_HOURS["images"]
    )


def test_stall_outcome_for_images_reports_photo_count_and_partial_detail() -> None:
    state = RunState(job_id=uuid4(), job_type=JobType.REFRESH, url="https://example.test")
    state.property_images = [
        PropertyImageIn(
            source_url="https://example.test/a.jpg",
            storage_path="properties/x/a.webp",
            content_hash="a",
            width=100,
            height=100,
            byte_size=10,
            kind="listing_photo",
        ),
        PropertyImageIn(
            source_url="https://example.test/plan.jpg",
            storage_path="properties/x/plan.webp",
            content_hash="p",
            width=100,
            height=100,
            byte_size=10,
            kind="floor_plan_diagram",
        ),
    ]
    state.warnings = [
        StageWarning(
            stage="IMAGE_FETCH",
            code="image_fetch_partial",
            message="2 image candidates could not be downloaded",
            detail={"failed_candidates": 2, "prepared_images": 1},
        )
    ]
    code, detail = _stall_outcome_for_class(state, "images")
    assert code == "images_partial"
    # Diagrams do not count toward the photo count the progress check compares.
    assert detail == {"photo_count": 1, "failed_candidates": 2, "prepared_images": 1}


def test_stall_outcome_for_reviews_reports_enrich_warning() -> None:
    state = RunState(job_id=uuid4(), job_type=JobType.REFRESH, url="https://example.test")
    state.warnings = [
        StageWarning(
            stage="ENRICH",
            code="reviews_refresh_failed",
            message="Places lookup failed",
            detail={"provider": "places"},
        )
    ]
    code, detail = _stall_outcome_for_class(state, "reviews")
    assert code == "reviews_refresh_failed"
    assert detail == {"message": "Places lookup failed", "provider": "places"}


async def test_record_refresh_stall_resets_streak_on_image_progress(
    pg_pool: asyncpg.Pool,
) -> None:
    hunt_id, property_id, listing_id, owner_id = uuid4(), uuid4(), uuid4(), uuid4()
    await pg_pool.execute(
        "insert into hunts (id, name, owner_id) values ($1, 'Stall progress', $2)",
        hunt_id,
        owner_id,
    )
    await pg_pool.execute(
        "insert into properties (id, name, canonical_address) values ($1, 'P', '1 St')",
        property_id,
    )
    await pg_pool.execute(
        "insert into hunt_listings (id, hunt_id, property_id, added_by) values ($1, $2, $3, $4)",
        listing_id,
        hunt_id,
        property_id,
        owner_id,
    )
    try:
        async with pg_pool.acquire() as conn:
            await _record_refresh_stall(
                conn,
                hunt_listing_id=listing_id,
                refresh_class="images",
                outcome_code="images_partial",
                detail={"photo_count": 10},
            )
            await _record_refresh_stall(
                conn,
                hunt_listing_id=listing_id,
                refresh_class="images",
                outcome_code="images_partial",
                detail={"photo_count": 10},
            )
            row = await conn.fetchrow(
                "select consecutive_stalls from hunt_listing_refresh_stalls "
                "where hunt_listing_id = $1 and refresh_class = 'images'",
                listing_id,
            )
            assert row["consecutive_stalls"] == 2

            # More photos found this attempt: progress, so the streak resets.
            await _record_refresh_stall(
                conn,
                hunt_listing_id=listing_id,
                refresh_class="images",
                outcome_code="images_partial",
                detail={"photo_count": 14},
            )
            row = await conn.fetchrow(
                "select consecutive_stalls, last_outcome_detail from hunt_listing_refresh_stalls "
                "where hunt_listing_id = $1 and refresh_class = 'images'",
                listing_id,
            )
            assert row["consecutive_stalls"] == 1
            stored_detail = json.loads(row["last_outcome_detail"])
            assert stored_detail["progressed"] is True

            await _clear_refresh_stall(conn, hunt_listing_id=listing_id, refresh_class="images")
            row = await conn.fetchrow(
                "select 1 from hunt_listing_refresh_stalls "
                "where hunt_listing_id = $1 and refresh_class = 'images'",
                listing_id,
            )
            assert row is None
    finally:
        await pg_pool.execute("delete from hunts where id = $1", hunt_id)
        await pg_pool.execute("delete from properties where id = $1", property_id)


async def test_record_refresh_stall_images_flat_cooldown_then_manual_reset(
    pg_pool: asyncpg.Pool,
) -> None:
    """Images stalls use a flat cooldown capped at `IMAGE_REFRESH_STALL_MAX_ATTEMPTS`
    attempts, then fall back to the 60-day images TTL; a manual attempt that
    still stalls resets the budget instead of extending that fallback."""
    hunt_id, property_id, listing_id, owner_id = uuid4(), uuid4(), uuid4(), uuid4()
    await pg_pool.execute(
        "insert into hunts (id, name, owner_id) values ($1, 'Image cooldown', $2)",
        hunt_id,
        owner_id,
    )
    await pg_pool.execute(
        "insert into properties (id, name, canonical_address) values ($1, 'P', '1 St')",
        property_id,
    )
    await pg_pool.execute(
        "insert into hunt_listings (id, hunt_id, property_id, added_by) values ($1, $2, $3, $4)",
        listing_id,
        hunt_id,
        property_id,
        owner_id,
    )
    try:
        async with pg_pool.acquire() as conn:
            for _ in range(IMAGE_REFRESH_STALL_MAX_ATTEMPTS - 1):
                await _record_refresh_stall(
                    conn,
                    hunt_listing_id=listing_id,
                    refresh_class="images",
                    outcome_code="images_partial",
                    detail={"photo_count": 30},
                )
            row = await conn.fetchrow(
                "select consecutive_stalls, next_eligible_at from hunt_listing_refresh_stalls "
                "where hunt_listing_id = $1 and refresh_class = 'images'",
                listing_id,
            )
            assert row["consecutive_stalls"] == IMAGE_REFRESH_STALL_MAX_ATTEMPTS - 1
            wait = row["next_eligible_at"] - datetime.now(UTC)
            assert (
                timedelta(hours=IMAGE_REFRESH_STALL_COOLDOWN_HOURS - 1)
                < wait
                <= timedelta(hours=IMAGE_REFRESH_STALL_COOLDOWN_HOURS)
            )

            # The Nth consecutive stall (gallery still stuck at 30) falls back
            # to the images TTL instead of another flat-cooldown retry.
            await _record_refresh_stall(
                conn,
                hunt_listing_id=listing_id,
                refresh_class="images",
                outcome_code="images_partial",
                detail={"photo_count": 30},
            )
            row = await conn.fetchrow(
                "select consecutive_stalls, next_eligible_at from hunt_listing_refresh_stalls "
                "where hunt_listing_id = $1 and refresh_class = 'images'",
                listing_id,
            )
            assert row["consecutive_stalls"] == IMAGE_REFRESH_STALL_MAX_ATTEMPTS
            wait = row["next_eligible_at"] - datetime.now(UTC)
            assert wait > timedelta(days=59)

            # A manual retry (the drawer's refresh button) that still stalls
            # resets the streak to a fresh flat-cooldown attempt rather than
            # leaving the Listing parked on the 60-day fallback.
            await _record_refresh_stall(
                conn,
                hunt_listing_id=listing_id,
                refresh_class="images",
                outcome_code="images_partial",
                detail={"photo_count": 30},
                manual=True,
            )
            row = await conn.fetchrow(
                "select consecutive_stalls, next_eligible_at from hunt_listing_refresh_stalls "
                "where hunt_listing_id = $1 and refresh_class = 'images'",
                listing_id,
            )
            assert row["consecutive_stalls"] == 1
            wait = row["next_eligible_at"] - datetime.now(UTC)
            assert (
                timedelta(hours=IMAGE_REFRESH_STALL_COOLDOWN_HOURS - 1)
                < wait
                <= timedelta(hours=IMAGE_REFRESH_STALL_COOLDOWN_HOURS)
            )
    finally:
        await pg_pool.execute("delete from hunts where id = $1", hunt_id)
        await pg_pool.execute("delete from properties where id = $1", property_id)


async def test_reconcile_refresh_classes_marks_success_and_records_stall(
    pg_pool: asyncpg.Pool,
) -> None:
    hunt_id, property_id, listing_id = uuid4(), uuid4(), uuid4()
    owner_id, job_id = uuid4(), uuid4()
    await pg_pool.execute(
        "insert into hunts (id, name, owner_id) values ($1, 'Reconcile', $2)", hunt_id, owner_id
    )
    await pg_pool.execute(
        "insert into properties (id, name, canonical_address) values ($1, 'P', '1 St')",
        property_id,
    )
    await pg_pool.execute(
        "insert into hunt_listings (id, hunt_id, property_id, added_by) values ($1, $2, $3, $4)",
        listing_id,
        hunt_id,
        property_id,
        owner_id,
    )
    # A prior pricing stall should be cleared once pricing succeeds again.
    await pg_pool.execute(
        """
        insert into hunt_listing_refresh_stalls
            (hunt_listing_id, refresh_class, consecutive_stalls,
             last_outcome_code, next_eligible_at)
        values ($1, 'pricing', 3, 'job_failed', now() + interval '12 hours')
        """,
        listing_id,
    )
    # _mark_refresh_classes_current's producer_job_id is FK'd to jobs.
    await pg_pool.execute(
        """
        insert into jobs (id, hunt_id, hunt_listing_id, type, state)
        values ($1, $2, $3, 'refresh', 'running')
        """,
        job_id,
        hunt_id,
        listing_id,
    )
    try:
        state = RunState(job_id=job_id, job_type=JobType.REFRESH, url="https://example.test")
        state.refresh_fields = ["pricing", "reviews"]
        state.warnings = [
            StageWarning(
                stage="ENRICH",
                code="reviews_refresh_failed",
                message="Places lookup failed",
                detail={},
            )
        ]
        async with pg_pool.acquire() as conn:
            successful = await _reconcile_refresh_classes(
                conn,
                hunt_listing_id=listing_id,
                job_id=job_id,
                state=state,
                requested_fields=state.refresh_fields,
            )
        assert successful == ["pricing"]

        pricing_status = await pg_pool.fetchrow(
            "select producer_job_id from hunt_listing_refresh_status "
            "where hunt_listing_id = $1 and refresh_class = 'pricing'",
            listing_id,
        )
        assert pricing_status is not None
        assert pricing_status["producer_job_id"] == job_id

        pricing_stall = await pg_pool.fetchrow(
            "select 1 from hunt_listing_refresh_stalls "
            "where hunt_listing_id = $1 and refresh_class = 'pricing'",
            listing_id,
        )
        assert pricing_stall is None

        reviews_stall = await pg_pool.fetchrow(
            "select consecutive_stalls, last_outcome_code from hunt_listing_refresh_stalls "
            "where hunt_listing_id = $1 and refresh_class = 'reviews'",
            listing_id,
        )
        assert reviews_stall is not None
        assert reviews_stall["consecutive_stalls"] == 1
        assert reviews_stall["last_outcome_code"] == "reviews_refresh_failed"
    finally:
        await pg_pool.execute("delete from hunts where id = $1", hunt_id)
        await pg_pool.execute("delete from properties where id = $1", property_id)


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


async def test_refresh_ttl_tick_uses_10_day_pricing_ttl_and_coalesces(
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
            (listing_id, "pricing", now - timedelta(days=10, minutes=1)),
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
    owner_id, source_id = uuid4(), uuid4()
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
    # Images never advanced (no row in hunt_listing_refresh_status), so it is
    # always TTL-due; a prior partial attempt left a backoff record instead.
    await pg_pool.execute(
        """
        insert into hunt_listing_refresh_stalls
            (hunt_listing_id, refresh_class, consecutive_stalls,
             last_outcome_code, next_eligible_at)
        values ($1, 'images', 1, 'images_partial', $2)
        """,
        listing_id,
        now + timedelta(hours=3),
    )
    try:
        await refresh_ttl_tick(pg_pool)
        count = await pg_pool.fetchval(
            "select count(*) from jobs where hunt_listing_id = $1 and type = 'refresh'",
            listing_id,
        )
        assert count == 0

        await pg_pool.execute(
            """
            update hunt_listing_refresh_stalls set next_eligible_at = now() - interval '1 minute'
            where hunt_listing_id = $1 and refresh_class = 'images'
            """,
            listing_id,
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
    seed_source_id, real_source_id = uuid4(), uuid4()
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
    stale = datetime.now(UTC) - timedelta(days=10, minutes=1)
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
    # A prior class-scoped refresh failed for the real Listing's pricing class
    # and left a durable backoff record (what _record_refresh_stall writes).
    await pg_pool.execute(
        """
        insert into hunt_listing_refresh_stalls
            (hunt_listing_id, refresh_class, consecutive_stalls,
             last_outcome_code, next_eligible_at)
        values ($1, 'pricing', 1, 'job_failed', now() + interval '1 hour')
        """,
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
            """
            update hunt_listing_refresh_stalls set next_eligible_at = now() - interval '1 minute'
            where hunt_listing_id = $1 and refresh_class = 'pricing'
            """,
            real_listing_id,
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
