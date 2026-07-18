"""P3-8: the `refresh` (scope: enrich) dispatcher — the proximity-flip path.

Re-derives `grocery_proximity` for every active listing at the hunt's current
`proximity_mode` against the properties geocode forever-cache, appends the
extraction rows (hunt_id NULL, source_id NULL — API-derived, not page facts),
and rescores. Maps seams injected; zero LLM calls by construction.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any
from uuid import uuid4

import asyncpg
import pytest
from manzil_shared.catalog import CATALOG
from manzil_shared.models import JobType
from manzil_worker.queue import make_enrich_refresh_dispatcher, run_worker_loop

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
)
SETTINGS = {
    "default_source_policy": "tiers_1_2_3",
    "cost_estimate_mode": "conservative",
    "min_confidence": "medium",
    "proximity_mode": "walking",
}
KROGER = {"name": "Kroger", "place_id": "ChIJkroger", "lat": 42.31, "lng": -83.06}


async def _fake_nearby(lat: float, lng: float, keyword: str) -> list[dict[str, Any]]:
    return [KROGER]


class CommuteLog:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def __call__(self, origin: str, destination: str, mode: str) -> float | None:
        self.calls.append((origin, destination, mode))
        return 12.0


async def _seed(pool: asyncpg.Pool) -> tuple:  # type: ignore[no-untyped-def]
    hunt_id, listing_id, property_id, source_id = uuid4(), uuid4(), uuid4(), uuid4()
    user_id = uuid4()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            insert into hunts (id, name, owner_id, settings, rubric_version)
            values ($1, 'EnrichRefresh', $2, $3::jsonb, 1)
            """,
            hunt_id,
            user_id,
            json.dumps(SETTINGS),
        )
        # A one-criterion rubric: grocery_proximity with the catalog defaults, no
        # gate-bearing criteria — an unscored gate would fire on unknown and empty
        # the breakdown's criteria list (§9.3), hiding exactly what this asserts.
        grocery = next(e for e in CATALOG if e.key == "grocery_proximity")
        await conn.execute(
            """
            insert into rubric_criteria (
                hunt_id, catalog_key, options, unknown_delta, is_bonus, position
            )
            values ($1, 'grocery_proximity', $2::jsonb, 0, false, 0)
            """,
            hunt_id,
            json.dumps(
                [o.model_dump(mode="json", exclude_none=True) for o in grocery.default_options]
            ),
        )
        # Geocode forever-cache is warm: no geocode call needed on refresh.
        await conn.execute(
            """
            insert into properties (id, name, canonical_address, place_id, lat, lng)
            values ($1, 'Test', '123 Maple Ct', 'ChIJmaple', 42.30, -83.05)
            """,
            property_id,
        )
        await conn.execute(
            """
            insert into property_sources (id, property_id, url, site_domain, cleaned_text_hash)
            values ($1, $2, $3, 'example.com', 'abc')
            """,
            source_id,
            property_id,
            f"https://example.com/p/{uuid4()}",
        )
        await conn.execute(
            "insert into hunt_listings (id, hunt_id, property_id, added_by) values ($1,$2,$3,$4)",
            listing_id,
            hunt_id,
            property_id,
            user_id,
        )
        await conn.execute(
            """
            insert into floor_plans
                (property_id, source_id, plan_name, beds, baths, rent_min, rent_max)
            values ($1, $2, '2x2', 2, 2.0, 1800, 1900)
            """,
            property_id,
            source_id,
        )
    return hunt_id, listing_id, property_id


async def _pool_or_skip() -> asyncpg.Pool:
    try:
        return await asyncpg.create_pool(DATABASE_URL, timeout=5, min_size=1, max_size=4)
    except (OSError, asyncpg.PostgresError) as exc:  # pragma: no cover
        pytest.skip(f"Postgres unreachable at {DATABASE_URL}: {exc}")


async def test_enrich_refresh_rederives_grocery_and_rescores() -> None:
    pool = await _pool_or_skip()
    hunt_id, listing_id, property_id = await _seed(pool)
    commute = CommuteLog()
    try:
        async with pool.acquire() as conn:
            job_id = await conn.fetchval(
                """
                insert into jobs (hunt_id, type, state, payload)
                values ($1, 'refresh', 'queued', $2::jsonb)
                returning id
                """,
                hunt_id,
                json.dumps({"hunt_id": str(hunt_id), "scope": "enrich"}),
            )
        dispatch = {
            JobType.REFRESH: make_enrich_refresh_dispatcher(
                nearby_places=_fake_nearby, commute_minutes=commute
            )
        }
        await run_worker_loop(pool, asyncio.Event(), dispatch=dispatch, until_empty=True)

        async with pool.acquire() as conn:
            state = await conn.fetchval("select state from jobs where id = $1", job_id)
            assert state == "done"
            row = await conn.fetchrow(
                """
                select value, confidence, source_id, model from extractions
                where property_id = $1 and criterion_key = 'grocery_proximity'
                order by extracted_at desc limit 1
                """,
                property_id,
            )
            assert row is not None
            assert json.loads(row["value"]) == 12.0
            assert row["source_id"] is None  # API-derived, never page provenance
            assert row["model"] == "maps"
            # The hunt's walking mode reached the commute call.
            assert commute.calls and commute.calls[0][2] == "walking"
            breakdown = await conn.fetchval(
                "select breakdown from scores where hunt_listing_id = $1",
                listing_id,
            )
            assert breakdown is not None
            grocery = next(
                c
                for c in json.loads(breakdown)["criteria"]
                if c["key"] == "grocery_proximity"
            )
            assert grocery["value"] == 12.0
    finally:
        await pool.execute("delete from hunts where id = $1", hunt_id)
        await pool.execute("delete from properties where id = $1", property_id)
        await pool.close()


async def test_refresh_unsupported_scope_fails_cleanly() -> None:
    pool = await _pool_or_skip()
    hunt_id = uuid4()
    async with pool.acquire() as conn:
        await conn.execute(
            "insert into hunts (id, name, owner_id) values ($1, 'X', $2)", hunt_id, uuid4()
        )
        job_id = await conn.fetchval(
            """
            insert into jobs (hunt_id, type, state, payload)
            values ($1, 'refresh', 'queued', $2::jsonb)
            returning id
            """,
            hunt_id,
            json.dumps({"hunt_id": str(hunt_id)}),  # no scope
        )
    try:
        dispatch = {JobType.REFRESH: make_enrich_refresh_dispatcher()}
        await run_worker_loop(pool, asyncio.Event(), dispatch=dispatch, until_empty=True)
        async with pool.acquire() as conn:
            row = await conn.fetchrow("select state, error from jobs where id = $1", job_id)
            assert row["state"] == "failed"
            assert "unsupported scope" in row["error"]
    finally:
        await pool.execute("delete from hunts where id = $1", hunt_id)
        await pool.close()
