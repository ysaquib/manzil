"""P3-7a DB projection: image URLs + idempotent current hash rows."""

from __future__ import annotations

import json
from uuid import uuid4

import asyncpg
from manzil_shared.models import JobType
from manzil_worker.queue import _persist_ingest_results
from manzil_worker.state import PropertyImageIn, RunState, SourceState


async def test_image_projection_upserts_and_prunes_complete_set(pg_pool: asyncpg.Pool) -> None:
    hunt_id, property_id, listing_id = uuid4(), uuid4(), uuid4()
    url = f"https://images.test/{uuid4()}"
    await pg_pool.execute(
        "insert into hunts (id, name, owner_id) values ($1, 'images', $2)", hunt_id, uuid4()
    )
    await pg_pool.execute(
        "insert into properties (id, name, canonical_address) values ($1, 'p', 'p')",
        property_id,
    )
    await pg_pool.execute(
        "insert into hunt_listings (id, hunt_id, property_id, added_by) "
        "values ($1, $2, $3, $4)",
        listing_id,
        hunt_id,
        property_id,
        uuid4(),
    )
    try:
        state = RunState(job_id=uuid4(), job_type=JobType.INGEST, url=url)
        state.sources = [
            SourceState(url=url, cleaned_hash="page-1", image_urls=["https://cdn/a", "https://cdn/b"])
        ]
        state.property_images = [
            PropertyImageIn(
                source_url="https://cdn/a",
                storage_path=f"properties/{property_id}/a.webp",
                content_hash="a",
                width=1024,
                height=700,
                byte_size=100,
                vision_assessment={"kind": "kitchen"},
            ),
            PropertyImageIn(
                source_url="https://cdn/b",
                storage_path=f"properties/{property_id}/b.webp",
                content_hash="b",
                width=800,
                height=600,
                byte_size=90,
            ),
        ]
        state.image_fetch_completed = True
        async with pg_pool.acquire() as conn, conn.transaction():
            await _persist_ingest_results(
                conn,
                hunt_listing_id=listing_id,
                property_id=property_id,
                rubric_version=1,
                state=state,
            )
        image_urls = await pg_pool.fetchval(
            "select image_urls from property_sources where url = $1", url
        )
        assert json.loads(image_urls) == ["https://cdn/a", "https://cdn/b"]
        assert await pg_pool.fetchval(
            "select count(*) from property_images where property_id = $1", property_id
        ) == 2

        # A complete second set contains only hash a. Row a is updated in place,
        # its prior assessment survives a null pre-VISION projection, and b prunes.
        state.property_images = [
            state.property_images[0].model_copy(update={"vision_assessment": None})
        ]
        async with pg_pool.acquire() as conn, conn.transaction():
            await _persist_ingest_results(
                conn,
                hunt_listing_id=listing_id,
                property_id=property_id,
                rubric_version=1,
                state=state,
            )
        rows = await pg_pool.fetch(
            "select content_hash, vision_assessment from property_images where property_id = $1",
            property_id,
        )
        assert [(row["content_hash"], row["vision_assessment"]) for row in rows] == [
            ("a", '{"kind": "kitchen"}')
        ]
    finally:
        await pg_pool.execute("delete from hunts where id = $1", hunt_id)
        await pg_pool.execute("delete from properties where id = $1", property_id)
