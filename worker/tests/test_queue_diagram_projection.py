"""P3-SC5 projection: Source-local image retirement and same-Source association.

Both rules are data-loss guards that only fail on multi-Source Properties — the
exact shape the DISCOVER slate produces — so they get a real projection run
rather than a unit test of the SQL.
"""

from __future__ import annotations

from uuid import uuid4

import asyncpg
from manzil_shared.models import FetchOutcome, JobType
from manzil_worker.queue import _persist_ingest_results
from manzil_worker.state import (
    FloorPlanIn,
    PlanScore,
    PropertyImageIn,
    RunState,
    SourceState,
)

OFFICIAL = "https://maplecourt.test"
OTHER = "https://aggregator.test/maple"


async def _seed(pool: asyncpg.Pool) -> tuple:  # type: ignore[no-untyped-def]
    hunt_id, property_id, listing_id = uuid4(), uuid4(), uuid4()
    await pool.execute(
        "insert into hunts (id, name, owner_id) values ($1, 'test', $2)", hunt_id, uuid4()
    )
    await pool.execute(
        "insert into properties (id, name, canonical_address) values ($1, 'P', 'addr')",
        property_id,
    )
    await pool.execute(
        "insert into hunt_listings (id, hunt_id, property_id, added_by) values ($1, $2, $3, $4)",
        listing_id,
        hunt_id,
        property_id,
        uuid4(),
    )
    return hunt_id, property_id, listing_id


async def _cleanup(pool: asyncpg.Pool, hunt_id, property_id) -> None:  # type: ignore[no-untyped-def]
    await pool.execute("delete from hunts where id = $1", hunt_id)
    await pool.execute("delete from properties where id = $1", property_id)


def _image(digest: str, page: str, *, refs: list[str] | None = None) -> PropertyImageIn:
    return PropertyImageIn(
        source_url=f"{page}/{digest}.png",
        storage_path=f"shared/{digest}.webp",
        content_hash=digest,
        width=2048,
        height=1400,
        byte_size=1000,
        kind="floor_plan_diagram",
        source_url_page=page,
        source_page_order=0,
        exact_floor_plan_refs=refs or [],
        discovery_context={"containing_floor_plan_card": True},
    )


def _state(url: str, *, images: list[PropertyImageIn], plans: list[FloorPlanIn]) -> RunState:
    state = RunState(job_id=uuid4(), job_type=JobType.INGEST, url=url)
    state.sources = [
        SourceState(
            url=url, tier_used=1, outcome=FetchOutcome.SUCCESS, cleaned_text="x", cleaned_hash="h"
        )
    ]
    state.floor_plans = plans
    state.property_images = images
    state.image_fetch_completed = True
    # SCORE emits one PlanScore per scorable plan; the projection zips them
    # strictly, so the fixture has to honour that contract.
    state.scores = [
        PlanScore(
            plan_name=plan.plan_name,
            breakdown={"base": 10, "total": 10, "rubric_version": 1,
                       "clamped": False, "gates": [], "criteria": []},
        )
        for plan in plans
    ]
    return state


async def _run(pool: asyncpg.Pool, listing_id, property_id, state: RunState) -> None:  # type: ignore[no-untyped-def]
    async with pool.acquire() as conn, conn.transaction():
        await _persist_ingest_results(
            conn,
            hunt_listing_id=listing_id,
            property_id=property_id,
            rubric_version=1,
            state=state,
        )


async def test_refreshing_one_source_never_retires_another_sources_images(
    pg_pool: asyncpg.Pool,
) -> None:
    """Refresh authority is Source-local (DESIGN §refresh).

    Before this fix the projection swept the whole Property, so re-running an
    aggregator quietly retired every diagram the official site had contributed.
    """
    hunt_id, property_id, listing_id = await _seed(pg_pool)
    try:
        await _run(
            pg_pool,
            listing_id,
            property_id,
            _state(OFFICIAL, images=[_image("aa" * 16, OFFICIAL)], plans=[]),
        )
        await _run(
            pg_pool,
            listing_id,
            property_id,
            _state(OTHER, images=[_image("bb" * 16, OTHER)], plans=[]),
        )

        # The second run contributed a different hash from a different Source.
        # Both must remain current.
        current = {
            row["content_hash"]
            for row in await pg_pool.fetch(
                "select content_hash from property_images "
                "where property_id = $1 and is_current",
                property_id,
            )
        }
        assert current == {"aa" * 16, "bb" * 16}
    finally:
        await _cleanup(pg_pool, hunt_id, property_id)


async def test_a_sources_own_vanished_image_is_still_retired(pg_pool: asyncpg.Pool) -> None:
    """Source-local must not mean toothless: a complete refresh of one Source
    still retires that Source's own images when they disappear."""
    hunt_id, property_id, listing_id = await _seed(pg_pool)
    try:
        await _run(
            pg_pool,
            listing_id,
            property_id,
            _state(OFFICIAL, images=[_image("aa" * 16, OFFICIAL)], plans=[]),
        )
        await _run(
            pg_pool,
            listing_id,
            property_id,
            _state(OFFICIAL, images=[_image("cc" * 16, OFFICIAL)], plans=[]),
        )

        rows = {
            row["content_hash"]: row["is_current"]
            for row in await pg_pool.fetch(
                "select content_hash, is_current from property_images where property_id = $1",
                property_id,
            )
        }
        assert rows["aa" * 16] is False
        assert rows["cc" * 16] is True
    finally:
        await _cleanup(pg_pool, hunt_id, property_id)


async def test_a_partial_fetch_retires_nothing(pg_pool: asyncpg.Pool) -> None:
    hunt_id, property_id, listing_id = await _seed(pg_pool)
    try:
        await _run(
            pg_pool,
            listing_id,
            property_id,
            _state(OFFICIAL, images=[_image("aa" * 16, OFFICIAL)], plans=[]),
        )
        partial = _state(OFFICIAL, images=[_image("cc" * 16, OFFICIAL)], plans=[])
        partial.image_fetch_completed = False
        await _run(pg_pool, listing_id, property_id, partial)

        current = await pg_pool.fetchval(
            "select count(*) from property_images where property_id = $1 and is_current",
            property_id,
        )
        assert current == 2
    finally:
        await _cleanup(pg_pool, hunt_id, property_id)


async def test_cap_saturated_partial_does_not_unlink_diagrams(pg_pool: asyncpg.Pool) -> None:
    hunt_id, property_id, listing_id = await _seed(pg_pool)
    try:
        await _run(
            pg_pool,
            listing_id,
            property_id,
            _state(
                OFFICIAL,
                plans=[
                    FloorPlanIn(
                        response_key="fp1", plan_name="Official Winslow", beds=2, baths=2
                    )
                ],
                images=[_image("aa" * 16, OFFICIAL, refs=["fp1"])],
            ),
        )
        cap_saturated = _state(OFFICIAL, images=[_image("cc" * 16, OFFICIAL)], plans=[])
        cap_saturated.image_fetch_completed = True
        cap_saturated.image_fetch_strict_complete = False
        await _run(pg_pool, listing_id, property_id, cap_saturated)

        links = await pg_pool.fetchval(
            "select count(*) from current_floor_plan_images c "
            "join floor_plans fp on fp.id = c.floor_plan_id "
            "where fp.property_id = $1",
            property_id,
        )
        assert links == 1
    finally:
        await _cleanup(pg_pool, hunt_id, property_id)


async def test_an_image_links_only_to_its_own_sources_floor_plan(
    pg_pool: asyncpg.Pool,
) -> None:
    """Response-local refs are Source-scoped. Two Sources can both emit `fp1`,
    and an image from one must never attach to the other's Floor Plan."""
    hunt_id, property_id, listing_id = await _seed(pg_pool)
    try:
        await _run(
            pg_pool,
            listing_id,
            property_id,
            _state(
                OFFICIAL,
                plans=[
                    FloorPlanIn(
                        response_key="fp1", plan_name="Official Winslow", beds=2, baths=2
                    )
                ],
                images=[_image("aa" * 16, OFFICIAL, refs=["fp1"])],
            ),
        )
        await _run(
            pg_pool,
            listing_id,
            property_id,
            _state(
                OTHER,
                plans=[
                    FloorPlanIn(
                        response_key="fp1", plan_name="Aggregator Harlow", beds=1, baths=1
                    )
                ],
                images=[_image("bb" * 16, OTHER, refs=["fp1"])],
            ),
        )

        links = await pg_pool.fetch(
            """
            select fp.plan_name, pi.content_hash
            from current_floor_plan_images c
            join floor_plans fp on fp.id = c.floor_plan_id
            join property_images pi on pi.id = c.property_image_id
            where fp.property_id = $1
            """,
            property_id,
        )
        pairs = {(row["plan_name"], row["content_hash"]) for row in links}
        assert pairs == {
            ("Official Winslow", "aa" * 16),
            ("Aggregator Harlow", "bb" * 16),
        }
    finally:
        await _cleanup(pg_pool, hunt_id, property_id)
