"""P3-4: `split_property` unmerge admin operation (DESIGN §10.3, §17 R5).

DB-backed, using the conftest `pg_pool` fixture and its skip-guard. No live LLM
or Google calls. Seeds the done-when scenario by hand (does NOT depend on the
DEDUPE stage): one merged Property P1 with two Sources, extractions + floor
plans split across the two source ids, two Hunts each with a Listing on P1,
ingest-job rows whose payloads carry URL1/URL2, and scores rows.
"""

from __future__ import annotations

import json
from uuid import UUID, uuid4

import asyncpg
import pytest
from manzil_shared.models import Confidence
from manzil_worker.ops.split_property import SplitError, split_property

URL1 = "https://apartments.com/riverfront-towers-detroit-mi/aaa111/"
URL2 = "https://zillow.com/autumn-ridge-detroit-mi/bbb222/"


class _Fixture:
    """Ids the seed hands back for assertions + cleanup."""

    def __init__(self) -> None:
        self.property_id = uuid4()
        self.hunt1_id = uuid4()
        self.hunt2_id = uuid4()
        self.listing1_id = uuid4()
        self.listing2_id = uuid4()
        self.source1_id = uuid4()
        self.source2_id = uuid4()
        self.fp1_id = uuid4()
        self.fp2_id = uuid4()
        # Populated after a successful split, so cleanup can drop the new row.
        self.new_property_id: UUID | None = None


async def _seed(pool: asyncpg.Pool, fx: _Fixture) -> None:
    user_id = uuid4()
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "insert into properties (id, name, canonical_address, place_id, lat, lng) "
            "values ($1, 'Merged Building', '1 Main St', 'PLACE_OLD', 42.3, -83.0)",
            fx.property_id,
        )
        for hunt_id in (fx.hunt1_id, fx.hunt2_id):
            await conn.execute(
                "insert into hunts (id, name, owner_id) values ($1, 'Hunt', $2)",
                hunt_id,
                user_id,
            )
        # Two Sources under the one Property.
        for source_id, url in ((fx.source1_id, URL1), (fx.source2_id, URL2)):
            await conn.execute(
                "insert into property_sources "
                "(id, property_id, url, site_domain, cleaned_text_hash) "
                "values ($1, $2, $3, 'example.com', 'h')",
                source_id,
                fx.property_id,
                url,
            )
        for url, suffix in ((URL1, "one"), (URL2, "two")):
            await conn.execute(
                "insert into property_images "
                "(property_id, source_url, storage_path, content_hash) "
                "values ($1, $2, $3, $4)",
                fx.property_id,
                url,
                f"properties/{fx.property_id}/{suffix}.webp",
                suffix,
            )
        # Candidate Extractions split across the two source ids (catalog facts:
        # hunt_id null). A separate test covers moving resolved companions.
        for source_id, key, value in (
            (fx.source1_id, "beds", "1"),
            (fx.source2_id, "beds", "2"),
            (fx.source2_id, "in_unit_laundry", '"in_unit"'),
        ):
            await conn.execute(
                "insert into extractions "
                "(property_id, hunt_id, criterion_key, record_kind, origin_key, "
                "source_id, target_scope, applicability, value, confidence, model) "
                "values ($1, null, $2, 'candidate', $5, $6, 'property', "
                "'unit_scope_unspecified', $3::jsonb, $4::confidence, 'test')",
                fx.property_id,
                key,
                value,
                Confidence.HIGH.value,
                f"property_source:{source_id}",
                source_id,
            )
        # Floor plans, one per source.
        for fp_id, source_id, name in (
            (fx.fp1_id, fx.source1_id, "1x1"),
            (fx.fp2_id, fx.source2_id, "2x2"),
        ):
            await conn.execute(
                "insert into floor_plans (id, property_id, source_id, plan_name, beds, baths) "
                "values ($1, $2, $3, $4, 2, 2.0)",
                fp_id,
                fx.property_id,
                source_id,
                name,
            )
        # Two Listings on P1, one per Hunt.
        for listing_id, hunt_id in (
            (fx.listing1_id, fx.hunt1_id),
            (fx.listing2_id, fx.hunt2_id),
        ):
            await conn.execute(
                "insert into hunt_listings (id, hunt_id, property_id, added_by) "
                "values ($1, $2, $3, $4)",
                listing_id,
                hunt_id,
                fx.property_id,
                user_id,
            )
        # Ingest jobs carrying each URL, wired to their Listing (the derivation input).
        for hunt_id, listing_id, url in (
            (fx.hunt1_id, fx.listing1_id, URL1),
            (fx.hunt2_id, fx.listing2_id, URL2),
        ):
            await conn.execute(
                "insert into jobs (hunt_id, hunt_listing_id, type, state, payload) "
                "values ($1, $2, 'ingest', 'done', $3::jsonb)",
                hunt_id,
                listing_id,
                json.dumps({"url": url}),
            )
        # Scores keyed on (listing, floor_plan) — must survive the split.
        for listing_id, fp_id in (
            (fx.listing1_id, fx.fp1_id),
            (fx.listing2_id, fx.fp2_id),
        ):
            await conn.execute(
                "insert into scores (hunt_listing_id, floor_plan_id, total, breakdown, "
                "rubric_version) values ($1, $2, 10, '{}'::jsonb, 1)",
                listing_id,
                fp_id,
            )


async def _cleanup(pool: asyncpg.Pool, fx: _Fixture) -> None:
    async with pool.acquire() as conn, conn.transaction():
        # Deleting hunts cascades hunt_listings -> scores and jobs (hunt_id FK).
        await conn.execute(
            "delete from hunts where id = any($1::uuid[])", [fx.hunt1_id, fx.hunt2_id]
        )
        # Deleting properties cascades property_sources -> floor_plans, and extractions.
        prop_ids = [fx.property_id]
        if fx.new_property_id is not None:
            prop_ids.append(fx.new_property_id)
        await conn.execute("delete from properties where id = any($1::uuid[])", prop_ids)


async def test_split_by_url_repoints_and_rescores(pg_pool: asyncpg.Pool) -> None:
    fx = _Fixture()
    await _seed(pg_pool, fx)
    try:
        async with pg_pool.acquire() as conn:
            result = await split_property(conn, property_id=fx.property_id, source_url=URL2)
        fx.new_property_id = result.new_property_id

        # New Property carries the placeholder identity, no geocode.
        prop = await pg_pool.fetchrow(
            "select name, canonical_address, place_id, lat, lng from properties where id = $1",
            result.new_property_id,
        )
        assert prop["name"] == "Autumn Ridge Detroit Mi"
        assert prop["canonical_address"] == "Autumn Ridge Detroit Mi"
        assert prop["place_id"] is None
        assert prop["lat"] is None and prop["lng"] is None

        # Source URL2 + its extractions + floor plan re-pointed to the new Property.
        src2_prop = await pg_pool.fetchval(
            "select property_id from property_sources where url = $1", URL2
        )
        assert src2_prop == result.new_property_id
        ext2 = await pg_pool.fetch(
            "select property_id from extractions where source_id = $1", fx.source2_id
        )
        assert ext2 and all(r["property_id"] == result.new_property_id for r in ext2)
        assert result.moved_extraction_count == 2
        fp2_prop = await pg_pool.fetchval(
            "select property_id from floor_plans where id = $1", fx.fp2_id
        )
        assert fp2_prop == result.new_property_id
        assert result.moved_floor_plan_count == 1
        assert result.moved_image_count == 1
        assert (
            await pg_pool.fetchval(
                "select property_id from property_images where source_url = $1", URL2
            )
            == result.new_property_id
        )
        assert (
            await pg_pool.fetchval(
                "select property_id from property_images where source_url = $1", URL1
            )
            == fx.property_id
        )

        # URL2-derived Listing moved; URL1 Listing untouched.
        assert result.moved_listing_ids == [fx.listing2_id]
        l2_prop = await pg_pool.fetchval(
            "select property_id from hunt_listings where id = $1", fx.listing2_id
        )
        assert l2_prop == result.new_property_id
        l1_prop = await pg_pool.fetchval(
            "select property_id from hunt_listings where id = $1", fx.listing1_id
        )
        assert l1_prop == fx.property_id

        # P1 keeps URL1's rows.
        assert (
            await pg_pool.fetchval("select property_id from property_sources where url = $1", URL1)
            == fx.property_id
        )
        assert (
            await pg_pool.fetchval("select property_id from floor_plans where id = $1", fx.fp1_id)
            == fx.property_id
        )
        assert all(
            r["property_id"] == fx.property_id
            for r in await pg_pool.fetch(
                "select property_id from extractions where source_id = $1", fx.source1_id
            )
        )

        # Scores survive the split (keyed on ids that did not change).
        assert (
            await pg_pool.fetchval(
                "select count(*) from scores where hunt_listing_id = $1 and floor_plan_id = $2",
                fx.listing2_id,
                fx.fp2_id,
            )
            == 1
        )

        # One rescore job per affected Hunt (both sides), with the right payload.
        assert sorted(result.rescored_hunt_ids) == sorted([fx.hunt1_id, fx.hunt2_id])
        rescore_jobs = await pg_pool.fetch(
            "select hunt_id, payload from jobs where type = 'rescore' and state = 'queued' "
            "and hunt_id = any($1::uuid[])",
            [fx.hunt1_id, fx.hunt2_id],
        )
        assert len(rescore_jobs) == 2
        for row in rescore_jobs:
            assert json.loads(row["payload"]) == {"hunt_id": str(row["hunt_id"])}
    finally:
        await _cleanup(pg_pool, fx)


async def test_unknown_source_url_errors(pg_pool: asyncpg.Pool) -> None:
    fx = _Fixture()
    await _seed(pg_pool, fx)
    try:
        async with pg_pool.acquire() as conn:
            with pytest.raises(SplitError, match="no property_source"):
                await split_property(
                    conn, property_id=fx.property_id, source_url="https://nope.test/x"
                )
    finally:
        await _cleanup(pg_pool, fx)


async def test_source_not_on_property_errors(pg_pool: asyncpg.Pool) -> None:
    fx = _Fixture()
    await _seed(pg_pool, fx)
    other_property_id = uuid4()
    try:
        async with pg_pool.acquire() as conn:
            # A wrong-but-real Property id: the Source exists, just not under it.
            with pytest.raises(SplitError, match="belongs to property"):
                await split_property(conn, property_id=other_property_id, source_url=URL2)
    finally:
        await _cleanup(pg_pool, fx)


async def test_single_source_property_refused(pg_pool: asyncpg.Pool) -> None:
    solo_property_id = uuid4()
    solo_url = "https://example.com/solo-building-detroit-mi/"
    await pg_pool.execute(
        "insert into properties (id, name, canonical_address) values ($1, 'Solo', 'addr')",
        solo_property_id,
    )
    await pg_pool.execute(
        "insert into property_sources (property_id, url, site_domain, cleaned_text_hash) "
        "values ($1, $2, 'example.com', 'h')",
        solo_property_id,
        solo_url,
    )
    try:
        async with pg_pool.acquire() as conn:
            with pytest.raises(SplitError, match="only 1 source"):
                await split_property(conn, property_id=solo_property_id, source_url=solo_url)
    finally:
        await pg_pool.execute("delete from properties where id = $1", solo_property_id)


async def test_explicit_listing_not_on_property_errors(pg_pool: asyncpg.Pool) -> None:
    fx = _Fixture()
    await _seed(pg_pool, fx)
    stray_listing_id = uuid4()
    try:
        async with pg_pool.acquire() as conn:
            with pytest.raises(SplitError, match="listings not on property"):
                await split_property(
                    conn,
                    property_id=fx.property_id,
                    source_url=URL2,
                    listing_ids=[stray_listing_id],
                )
        # The failed op wrote nothing — no new Property was created (rollback whole).
        assert (
            await pg_pool.fetchval("select property_id from property_sources where url = $1", URL2)
            == fx.property_id
        )
    finally:
        await _cleanup(pg_pool, fx)
