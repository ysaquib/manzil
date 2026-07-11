"""P1-6: rescore job type rescored listings from persisted extractions + overrides."""

from __future__ import annotations

import asyncio
import json
import os
from uuid import uuid4

import asyncpg
import pytest
from manzil_shared.models import Confidence
from manzil_worker.phase0_rubric import phase0_rubric
from manzil_worker.queue import build_dispatch, run_worker_loop

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
)
SETTINGS = {
    "default_source_policy": "tiers_1_2_3",
    "cost_estimate_mode": "conservative",
    "min_confidence": "medium",
    "proximity_mode": "driving",
}


async def _seed_rescore_fixture(pool: asyncpg.Pool) -> tuple:  # type: ignore[no-untyped-def]
    hunt_id, listing_id, property_id, source_id, floor_plan_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    user_id = uuid4()
    source_url = f"https://example.com/p/{uuid4()}"
    async with pool.acquire() as conn:
        await conn.execute(
            """
            insert into hunts (id, name, owner_id, settings, rubric_version)
            values ($1, 'Rescore', $2, $3::jsonb, 1)
            """,
            hunt_id,
            user_id,
            json.dumps(SETTINGS),
        )
        for crit in phase0_rubric():
            await conn.execute(
                """
                insert into rubric_criteria (
                    hunt_id, catalog_key, options, unknown_delta,
                    non_negotiable, is_bonus, position
                )
                values ($1, $2, $3::jsonb, $4, $5::jsonb, $6, $7)
                """,
                hunt_id,
                crit.catalog_key,
                json.dumps([o.model_dump(mode="json") for o in crit.options]),
                crit.unknown_delta,
                json.dumps(crit.non_negotiable.model_dump(mode="json"))
                if crit.non_negotiable
                else None,
                crit.is_bonus,
                crit.position,
            )
        await conn.execute(
            "insert into properties (id, name, canonical_address) values ($1, 'Test', 'addr')",
            property_id,
        )
        await conn.execute(
            """
            insert into property_sources (id, property_id, url, site_domain, cleaned_text_hash)
            values ($1, $2, $3, 'example.com', 'abc')
            """,
            source_id,
            property_id,
            source_url,
        )
        await conn.execute(
            """
            insert into hunt_listings (id, hunt_id, property_id, added_by)
            values ($1, $2, $3, $4)
            """,
            listing_id,
            hunt_id,
            property_id,
            user_id,
        )
        await conn.execute(
            """
            insert into floor_plans
                (id, property_id, source_id, plan_name, beds, baths, rent_min, rent_max)
            values ($1, $2, $3, '2x2', 2, 2.0, 1800, 1900)
            """,
            floor_plan_id,
            property_id,
            source_id,
        )
        # Extraction says 1 bed (would fail gate) — override should win.
        await conn.execute(
            """
            insert into extractions
                (property_id, hunt_id, criterion_key, value, confidence, model)
            values ($1, null, 'beds', '1'::jsonb, $2::confidence, 'test')
            """,
            property_id,
            Confidence.HIGH.value,
        )
        await conn.execute(
            """
            insert into extractions
                (property_id, hunt_id, criterion_key, value, confidence, model)
            values ($1, null, 'in_unit_laundry', '"in_unit"'::jsonb, $2::confidence, 'test')
            """,
            property_id,
            Confidence.HIGH.value,
        )
        await conn.execute(
            """
            insert into extractions
                (property_id, hunt_id, criterion_key, value, confidence, model)
            values ($1, null, 'pets_policy', '"cats_only"'::jsonb, $2::confidence, 'test')
            """,
            property_id,
            Confidence.HIGH.value,
        )
        await conn.execute(
            """
            insert into overrides (hunt_listing_id, criterion_key, value, user_id)
            values ($1, 'beds', '2'::jsonb, $2)
            """,
            listing_id,
            user_id,
        )
    return hunt_id, listing_id, floor_plan_id


async def test_rescore_applies_override_and_persists_scores() -> None:
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, timeout=5, min_size=1, max_size=4)
    except (OSError, asyncpg.PostgresError) as exc:  # pragma: no cover
        pytest.skip(f"Postgres unreachable at {DATABASE_URL}: {exc}")

    hunt_id, listing_id, floor_plan_id = await _seed_rescore_fixture(pool)
    try:
        async with pool.acquire() as conn:
            job_id = await conn.fetchval(
                """
                insert into jobs (hunt_id, type, state, payload)
                values ($1, 'rescore', 'queued', $2::jsonb)
                returning id
                """,
                hunt_id,
                json.dumps({"hunt_id": str(hunt_id)}),
            )
        dispatch = build_dispatch(pool)
        await run_worker_loop(pool, asyncio.Event(), dispatch=dispatch, until_empty=True)

        async with pool.acquire() as conn:
            state = await conn.fetchval("select state from jobs where id = $1", job_id)
            assert state == "done"
            breakdown = await conn.fetchval(
                "select breakdown from scores where hunt_listing_id = $1 and floor_plan_id = $2",
                listing_id,
                floor_plan_id,
            )
            assert breakdown is not None
            parsed = json.loads(breakdown)
            beds_entry = next(c for c in parsed["criteria"] if c["key"] == "beds")
            assert beds_entry["value"] == 2
            assert parsed["rubric_version"] == 1
    finally:
        await pool.execute("delete from hunts where id = $1", hunt_id)
        await pool.close()


async def test_rescore_folds_pet_rent_from_fee_slots_and_settings() -> None:
    """§9.5 v1: rescore reads pet counts from hunt settings and per-pet rents from
    the fee_checklist slots (extracted OR manual), folding them into all_in_monthly.
    This is what makes a manual fee edit + a settings change genuinely rescore-
    effective."""
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, timeout=5, min_size=1, max_size=4)
    except (OSError, asyncpg.PostgresError) as exc:  # pragma: no cover
        pytest.skip(f"Postgres unreachable at {DATABASE_URL}: {exc}")

    hunt_id, listing_id, floor_plan_id = await _seed_rescore_fixture(pool)
    try:
        async with pool.acquire() as conn:
            # 1 cat + 1 dog on the hunt; cat rent extracted, dog rent entered manually.
            settings = {**SETTINGS, "cats": 1, "dogs": 1}
            await conn.execute(
                "update hunts set settings = $2::jsonb where id = $1",
                hunt_id,
                json.dumps(settings),
            )
            await conn.execute(
                """
                insert into fee_checklist (hunt_listing_id, fee_slot, amount, value_state)
                values ($1, 'pet_rent_cat', 20.00, 'extracted'),
                       ($1, 'pet_rent_dog', 35.00, 'manual')
                """,
                listing_id,
            )
            await conn.fetchval(
                """
                insert into jobs (hunt_id, type, state, payload)
                values ($1, 'rescore', 'queued', $2::jsonb) returning id
                """,
                hunt_id,
                json.dumps({"hunt_id": str(hunt_id)}),
            )
        dispatch = build_dispatch(pool)
        await run_worker_loop(pool, asyncio.Event(), dispatch=dispatch, until_empty=True)

        breakdown = await pool.fetchval(
            "select breakdown from scores where hunt_listing_id = $1 and floor_plan_id = $2",
            listing_id,
            floor_plan_id,
        )
        parsed = json.loads(breakdown)
        all_in = next(c for c in parsed["criteria"] if c["key"] == "all_in_monthly")
        # conservative rent 1900 + 1*20 (cat) + 1*35 (dog) = 1955
        assert all_in["value"] == 1955.0
    finally:
        await pool.execute("delete from hunts where id = $1", hunt_id)
        await pool.close()


async def test_rescore_after_rubric_version_bump_updates_all_scores() -> None:
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, timeout=5, min_size=1, max_size=4)
    except (OSError, asyncpg.PostgresError) as exc:  # pragma: no cover
        pytest.skip(f"Postgres unreachable at {DATABASE_URL}: {exc}")

    hunt_id, listing_id, floor_plan_id = await _seed_rescore_fixture(pool)
    try:
        async with pool.acquire() as conn:
            await conn.execute("update hunts set rubric_version = 2 where id = $1", hunt_id)
            await conn.fetchval(
                """
                insert into jobs (hunt_id, type, state, payload)
                values ($1, 'rescore', 'queued', $2::jsonb)
                returning id
                """,
                hunt_id,
                json.dumps({"hunt_id": str(hunt_id)}),
            )
        dispatch = build_dispatch(pool)
        await run_worker_loop(pool, asyncio.Event(), dispatch=dispatch, until_empty=True)

        version = await pool.fetchval(
            "select rubric_version from scores where hunt_listing_id = $1 and floor_plan_id = $2",
            listing_id,
            floor_plan_id,
        )
        assert version == 2
    finally:
        await pool.execute("delete from hunts where id = $1", hunt_id)
        await pool.close()
