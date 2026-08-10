"""P3-9: utility-baselines job + scheduler tick — regional keys, full coverage,
TTL freshness (all 24 rows), and scope-matched rescore fan-out."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import asyncpg
import manzil_worker.queue as queue_mod
import pytest
from manzil_worker.enrich.utility_baselines import (
    BASELINE_UTILITIES,
    BEDS_BUCKETS,
    BaselineRegion,
    baselines_for_region,
    due_baseline_regions,
    refresh_region_baselines,
    select_baseline_region,
)
from worker_helpers import FakeLLM

AMOUNTS = {
    "electric": (120.0, 80.0),
    "electric_heat": (220.0, 140.0),
    "gas_heat": (150.0, 90.0),
    "water": (55.0, 40.0),
    "sewer": (45.0, 35.0),
    "trash": (30.0, 25.0),
}


def _full_rows() -> list[dict]:  # type: ignore[type-arg]
    return [
        {
            "utility": utility,
            "beds_bucket": bucket,
            "monthly_high": AMOUNTS[utility][0] + bucket * 10,
            "monthly_median": AMOUNTS[utility][1] + bucket * 5,
        }
        for bucket in BEDS_BUCKETS
        for utility in BASELINE_UTILITIES
    ]


async def _cleanup_region(pool: asyncpg.Pool, region: BaselineRegion) -> None:
    await pool.execute(
        """
        delete from utility_baselines
        where geo_level = $1 and state = $2 and region_name = $3
        """,
        region.geo_level,
        region.state,
        region.region_name,
    )


async def _seed_listing(
    pool: asyncpg.Pool,
    *,
    city: str | None,
    state: str,
    county: str | None = None,
) -> tuple:
    hunt_id, property_id = uuid4(), uuid4()
    await pool.execute(
        "insert into hunts (id, name, owner_id) values ($1, 'B', $2)", hunt_id, uuid4()
    )
    await pool.execute(
        """
        insert into properties (id, name, canonical_address, city, state, county)
        values ($1, 'P', '1 Main', $2, $3, $4)
        """,
        property_id,
        city,
        state,
        county,
    )
    await pool.execute(
        "insert into hunt_listings (id, hunt_id, property_id, added_by) values ($1, $2, $3, $4)",
        uuid4(),
        hunt_id,
        property_id,
        uuid4(),
    )
    return hunt_id, property_id


def test_select_baseline_region_policy() -> None:
    assert select_baseline_region(
        city="Detroit", state="MI", county="Wayne County"
    ) == BaselineRegion("city", "MI", "Detroit")
    assert select_baseline_region(city=None, state="MI", county="Wayne County") == BaselineRegion(
        "county", "MI", "Wayne County"
    )
    assert select_baseline_region(city=None, state="MI", county=None) == BaselineRegion(
        "state", "MI", "MI"
    )
    assert select_baseline_region(city="Detroit", state=None, county=None) is None


async def test_refresh_writes_all_combos_and_clamps_high(pg_pool: asyncpg.Pool) -> None:
    region = BaselineRegion("city", "MI", f"TestVille-{uuid4().hex[:6]}")
    rows = _full_rows()
    rows[0] = {**rows[0], "monthly_high": 10.0, "monthly_median": 99.0}
    fake = FakeLLM({"utility_baselines": {"rows": rows, "sources": ["DTE Energy"]}})
    try:
        async with pg_pool.acquire() as conn:
            written = await refresh_region_baselines(conn, region, call_structured=fake)
        assert written == len(BEDS_BUCKETS) * len(BASELINE_UTILITIES)
        loaded = await baselines_for_region(pg_pool, region, 2)
        assert loaded is not None and set(loaded.values) == set(AMOUNTS)
        assert loaded.values["water"] == (75.0, 50.0)
        clamped = await pg_pool.fetchrow(
            """
            select monthly_high, monthly_median from utility_baselines
            where geo_level = $1 and state = $2 and region_name = $3
              and beds_bucket = $4 and utility = $5
            """,
            region.geo_level,
            region.state,
            region.region_name,
            rows[0]["beds_bucket"],
            rows[0]["utility"],
        )
        assert float(clamped["monthly_high"]) == 99.0
        sources = await pg_pool.fetchval(
            """
            select sources from utility_baselines
            where geo_level = $1 and state = $2 and region_name = $3 limit 1
            """,
            region.geo_level,
            region.state,
            region.region_name,
        )
        assert json.loads(sources) == {"search": False, "claimed": ["DTE Energy"]}
    finally:
        await _cleanup_region(pg_pool, region)


async def test_detroit_mi_and_detroit_oh_do_not_collide(pg_pool: asyncpg.Pool) -> None:
    mi = BaselineRegion("city", "MI", "Detroit")
    oh = BaselineRegion("city", "OH", "Detroit")
    fake = FakeLLM({"utility_baselines": {"rows": _full_rows(), "sources": ["local utility"]}})
    try:
        async with pg_pool.acquire() as conn:
            await refresh_region_baselines(conn, mi, call_structured=fake)
            await refresh_region_baselines(conn, oh, call_structured=fake)
        mi_loaded = await baselines_for_region(pg_pool, mi, 1)
        oh_loaded = await baselines_for_region(pg_pool, oh, 1)
        assert mi_loaded is not None and oh_loaded is not None
        mi_count = await pg_pool.fetchval(
            """
            select count(*) from utility_baselines
            where geo_level = 'city' and state = 'MI' and region_name = 'Detroit'
            """
        )
        oh_count = await pg_pool.fetchval(
            """
            select count(*) from utility_baselines
            where geo_level = 'city' and state = 'OH' and region_name = 'Detroit'
            """
        )
        assert mi_count == 24 and oh_count == 24
    finally:
        await _cleanup_region(pg_pool, mi)
        await _cleanup_region(pg_pool, oh)


async def test_incomplete_coverage_writes_nothing(pg_pool: asyncpg.Pool) -> None:
    region = BaselineRegion("city", "MI", f"GapTown-{uuid4().hex[:6]}")
    fake = FakeLLM({"utility_baselines": {"rows": _full_rows()[:-1], "sources": []}})
    try:
        async with pg_pool.acquire() as conn:
            with pytest.raises(ValueError, match="incomplete coverage"):
                await refresh_region_baselines(conn, region, call_structured=fake)
        count = await pg_pool.fetchval(
            """
            select count(*) from utility_baselines
            where geo_level = $1 and state = $2 and region_name = $3
            """,
            region.geo_level,
            region.state,
            region.region_name,
        )
        assert count == 0
    finally:
        await _cleanup_region(pg_pool, region)


async def test_due_regions_require_all_twenty_four_fresh_rows(pg_pool: asyncpg.Pool) -> None:
    city = f"Detroit-{uuid4().hex[:6]}"
    region = BaselineRegion("city", "MI", city)
    hunt_id, property_id = await _seed_listing(pg_pool, city=city, state="MI")
    try:
        async with pg_pool.acquire() as conn:
            due = await due_baseline_regions(conn)
            assert region in due
            await conn.execute(
                """
                insert into utility_baselines
                    (geo_level, state, region_name, beds_bucket, utility,
                     monthly_high, monthly_median)
                values ($1, $2, $3, 1, 'water', 50, 40)
                """,
                region.geo_level,
                region.state,
                region.region_name,
            )
            assert region in await due_baseline_regions(conn)
            for bucket in BEDS_BUCKETS:
                for utility in BASELINE_UTILITIES:
                    await conn.execute(
                        """
                        insert into utility_baselines
                            (geo_level, state, region_name, beds_bucket, utility,
                             monthly_high, monthly_median)
                        values ($1, $2, $3, $4, $5, 50, 40)
                        on conflict do nothing
                        """,
                        region.geo_level,
                        region.state,
                        region.region_name,
                        bucket,
                        utility,
                    )
            assert region not in await due_baseline_regions(conn)
            stale = datetime.now(UTC) - timedelta(days=121)
            await conn.execute(
                """
                update utility_baselines set refreshed_at = $4
                where geo_level = $1 and state = $2 and region_name = $3
                """,
                region.geo_level,
                region.state,
                region.region_name,
                stale,
            )
            assert region in await due_baseline_regions(conn)
    finally:
        await pg_pool.execute("delete from hunts where id = $1", hunt_id)
        await pg_pool.execute("delete from properties where id = $1", property_id)
        await _cleanup_region(pg_pool, region)


async def test_successful_pass_enqueues_scope_matched_rescores(
    pg_pool: asyncpg.Pool, monkeypatch: pytest.MonkeyPatch
) -> None:
    city = f"Ypsi-{uuid4().hex[:6]}"
    region = BaselineRegion("city", "MI", city)
    hunt_id, property_id = await _seed_listing(pg_pool, city=city, state="MI")

    async def fake_refresh(conn, r, **kwargs):  # type: ignore[no-untyped-def]
        return 24

    monkeypatch.setattr(
        "manzil_worker.enrich.utility_baselines.refresh_region_baselines", fake_refresh
    )
    try:
        await queue_mod._run_region_baselines(pg_pool, region)
        jobs = await pg_pool.fetch(
            "select payload from jobs where hunt_id = $1 and type = 'rescore' and state = 'queued'",
            hunt_id,
        )
        assert len(jobs) == 1
        assert json.loads(jobs[0]["payload"])["hunt_id"] == str(hunt_id)
    finally:
        await pg_pool.execute("delete from hunts where id = $1", hunt_id)
        await pg_pool.execute("delete from properties where id = $1", property_id)


async def test_failed_pass_enqueues_no_rescores(
    pg_pool: asyncpg.Pool, monkeypatch: pytest.MonkeyPatch
) -> None:
    city = f"FailField-{uuid4().hex[:6]}"
    region = BaselineRegion("city", "MI", city)
    hunt_id, property_id = await _seed_listing(pg_pool, city=city, state="MI")

    async def fake_refresh(conn, r, **kwargs):  # type: ignore[no-untyped-def]
        raise ValueError("incomplete coverage")

    monkeypatch.setattr(
        "manzil_worker.enrich.utility_baselines.refresh_region_baselines", fake_refresh
    )
    try:
        await queue_mod._run_region_baselines(pg_pool, region)
        count = await pg_pool.fetchval(
            "select count(*) from jobs where hunt_id = $1 and type = 'rescore'", hunt_id
        )
        assert count == 0
    finally:
        await pg_pool.execute("delete from hunts where id = $1", hunt_id)
        await pg_pool.execute("delete from properties where id = $1", property_id)


async def test_tick_spawns_one_guarded_pass_per_due_region(
    pg_pool: asyncpg.Pool, monkeypatch: pytest.MonkeyPatch
) -> None:
    city = f"City-{uuid4().hex[:6]}"
    region = BaselineRegion("city", "MI", city)
    hunt_id, property_id = await _seed_listing(pg_pool, city=city, state="MI")
    refreshed: list[str] = []

    async def fake_refresh(conn, r, **kwargs):  # type: ignore[no-untyped-def]
        refreshed.append(r.lock_key())
        return 24

    monkeypatch.setattr(
        "manzil_worker.enrich.utility_baselines.refresh_region_baselines", fake_refresh
    )
    key = region.lock_key()
    try:
        await queue_mod.utility_baselines_tick(pg_pool)
        pending = [t for k, t in queue_mod._BASELINE_TASKS.items() if k == key]
        await asyncio.gather(*pending)
        assert refreshed.count(key) == 1
        await queue_mod.utility_baselines_tick(pg_pool)
        await asyncio.gather(*[t for k, t in queue_mod._BASELINE_TASKS.items() if k == key])
        assert refreshed.count(key) == 1
        queue_mod._BASELINE_LAST_ATTEMPT.pop(key, None)
        await queue_mod.utility_baselines_tick(pg_pool)
        await asyncio.gather(*[t for k, t in queue_mod._BASELINE_TASKS.items() if k == key])
        assert refreshed.count(key) == 2
    finally:
        queue_mod._BASELINE_LAST_ATTEMPT.pop(key, None)
        await pg_pool.execute("delete from hunts where id = $1", hunt_id)
        await pg_pool.execute("delete from properties where id = $1", property_id)
