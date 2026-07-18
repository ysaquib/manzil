"""P3-9: utility-baselines job + scheduler tick — full-coverage upsert,
all-or-nothing rejection, TTL-driven due-metro selection, and the tick's
guarded task spawn. DB-backed via the pg_pool fixture."""

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
    baselines_for_metro,
    due_metros,
    refresh_metro_baselines,
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


async def _cleanup_metro(pool: asyncpg.Pool, metro: str) -> None:
    await pool.execute("delete from utility_baselines where metro = $1", metro)


async def test_refresh_writes_all_combos_and_clamps_high(pg_pool: asyncpg.Pool) -> None:
    metro = f"TestVille-{uuid4().hex[:6]}"
    rows = _full_rows()
    rows[0] = {**rows[0], "monthly_high": 10.0, "monthly_median": 99.0}  # median > high
    fake = FakeLLM({"utility_baselines": {"rows": rows, "sources": ["DTE Energy"]}})
    try:
        async with pg_pool.acquire() as conn:
            written = await refresh_metro_baselines(conn, metro, call_structured=fake)
        assert written == len(BEDS_BUCKETS) * len(BASELINE_UTILITIES)
        loaded = await baselines_for_metro(pg_pool, metro, 2)
        assert loaded is not None and set(loaded) == set(BASELINE_UTILITIES)
        assert loaded["water"] == (75.0, 50.0)  # bucket 2: 55+20, 40+10
        # The winter-weighted high can never sit below the median.
        clamped = await pg_pool.fetchrow(
            "select monthly_high, monthly_median from utility_baselines "
            "where metro = $1 and beds_bucket = $2 and utility = $3",
            metro,
            rows[0]["beds_bucket"],
            rows[0]["utility"],
        )
        assert float(clamped["monthly_high"]) == 99.0
        sources = await pg_pool.fetchval(
            "select sources from utility_baselines where metro = $1 limit 1", metro
        )
        assert json.loads(sources) == {"search": False, "claimed": ["DTE Energy"]}
    finally:
        await _cleanup_metro(pg_pool, metro)


async def test_incomplete_coverage_writes_nothing(pg_pool: asyncpg.Pool) -> None:
    metro = f"GapTown-{uuid4().hex[:6]}"
    fake = FakeLLM({"utility_baselines": {"rows": _full_rows()[:-1], "sources": []}})
    try:
        async with pg_pool.acquire() as conn:
            with pytest.raises(ValueError, match="incomplete coverage"):
                await refresh_metro_baselines(conn, metro, call_structured=fake)
        count = await pg_pool.fetchval(
            "select count(*) from utility_baselines where metro = $1", metro
        )
        assert count == 0
    finally:
        await _cleanup_metro(pg_pool, metro)


async def _seed_listing_in_metro(pool: asyncpg.Pool, metro: str) -> tuple:  # type: ignore[no-untyped-def]
    hunt_id, property_id = uuid4(), uuid4()
    await pool.execute(
        "insert into hunts (id, name, owner_id) values ($1, 'B', $2)", hunt_id, uuid4()
    )
    await pool.execute(
        "insert into properties (id, name, canonical_address, city) values ($1, 'P', '1 Main', $2)",
        property_id,
        metro,
    )
    await pool.execute(
        "insert into hunt_listings (id, hunt_id, property_id, added_by) values ($1, $2, $3, $4)",
        uuid4(),
        hunt_id,
        property_id,
        uuid4(),
    )
    return hunt_id, property_id


async def test_due_metros_follow_the_ttl(pg_pool: asyncpg.Pool) -> None:
    metro = f"Detroit-{uuid4().hex[:6]}"
    hunt_id, property_id = await _seed_listing_in_metro(pg_pool, metro)
    try:
        async with pg_pool.acquire() as conn:
            assert metro in await due_metros(conn)  # no rows at all → due
            await conn.execute(
                """
                insert into utility_baselines
                    (metro, beds_bucket, utility, monthly_high, monthly_median)
                values ($1, 1, 'water', 50, 40)
                """,
                metro,
            )
            assert metro not in await due_metros(conn)  # fresh row → covered
            stale = datetime.now(UTC) - timedelta(days=121)
            await conn.execute(
                "update utility_baselines set refreshed_at = $2 where metro = $1", metro, stale
            )
            assert metro in await due_metros(conn)  # past the 120 d TTL → due again
    finally:
        await pg_pool.execute("delete from hunts where id = $1", hunt_id)
        await pg_pool.execute("delete from properties where id = $1", property_id)
        await _cleanup_metro(pg_pool, metro)


async def test_successful_pass_enqueues_metro_rescores(
    pg_pool: asyncpg.Pool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A metro's first listing always scores before its baselines exist (the
    pass is triggered BY that listing), so a successful write must re-compose
    the metro's listings — one hunt-level rescore per affected hunt."""
    metro = f"Ypsi-{uuid4().hex[:6]}"
    hunt_id, property_id = await _seed_listing_in_metro(pg_pool, metro)

    async def fake_refresh(conn, m, **kwargs):  # type: ignore[no-untyped-def]
        return 24

    monkeypatch.setattr(
        "manzil_worker.enrich.utility_baselines.refresh_metro_baselines", fake_refresh
    )
    try:
        await queue_mod._run_metro_baselines(pg_pool, metro)
        jobs = await pg_pool.fetch(
            "select payload from jobs where hunt_id = $1 and type = 'rescore' "
            "and state = 'queued'",
            hunt_id,
        )
        assert len(jobs) == 1
        assert json.loads(jobs[0]["payload"])["hunt_id"] == str(hunt_id)
    finally:
        await pg_pool.execute("delete from hunts where id = $1", hunt_id)
        await pg_pool.execute("delete from properties where id = $1", property_id)
        await _cleanup_metro(pg_pool, metro)


async def test_failed_pass_enqueues_no_rescores(
    pg_pool: asyncpg.Pool, monkeypatch: pytest.MonkeyPatch
) -> None:
    metro = f"FailField-{uuid4().hex[:6]}"
    hunt_id, property_id = await _seed_listing_in_metro(pg_pool, metro)

    async def fake_refresh(conn, m, **kwargs):  # type: ignore[no-untyped-def]
        raise ValueError("incomplete coverage")

    monkeypatch.setattr(
        "manzil_worker.enrich.utility_baselines.refresh_metro_baselines", fake_refresh
    )
    try:
        await queue_mod._run_metro_baselines(pg_pool, metro)
        count = await pg_pool.fetchval(
            "select count(*) from jobs where hunt_id = $1 and type = 'rescore'", hunt_id
        )
        assert count == 0
    finally:
        await pg_pool.execute("delete from hunts where id = $1", hunt_id)
        await pg_pool.execute("delete from properties where id = $1", property_id)
        await _cleanup_metro(pg_pool, metro)


async def test_tick_spawns_one_guarded_pass_per_due_metro(
    pg_pool: asyncpg.Pool, monkeypatch: pytest.MonkeyPatch
) -> None:
    metro = f"City-{uuid4().hex[:6]}"
    hunt_id, property_id = await _seed_listing_in_metro(pg_pool, metro)
    refreshed: list[str] = []

    async def fake_refresh(conn, m, **kwargs):  # type: ignore[no-untyped-def]
        refreshed.append(m)
        return 24

    monkeypatch.setattr(
        "manzil_worker.enrich.utility_baselines.refresh_metro_baselines", fake_refresh
    )
    try:
        await queue_mod.utility_baselines_tick(pg_pool)
        # The tick spawns background tasks; drain the ones it registered.
        pending = [t for m, t in queue_mod._BASELINE_TASKS.items() if m == metro]
        await asyncio.gather(*pending)
        assert refreshed.count(metro) == 1
        # The metro is still due (the fake wrote nothing), but the attempt
        # cooldown holds — no once-per-tick live-call churn on a failing metro.
        await queue_mod.utility_baselines_tick(pg_pool)
        await asyncio.gather(
            *[t for m, t in queue_mod._BASELINE_TASKS.items() if m == metro]
        )
        assert refreshed.count(metro) == 1
        # Cooldown expiry (and the released advisory lock) allow the retry.
        queue_mod._BASELINE_LAST_ATTEMPT.pop(metro, None)
        await queue_mod.utility_baselines_tick(pg_pool)
        await asyncio.gather(
            *[t for m, t in queue_mod._BASELINE_TASKS.items() if m == metro]
        )
        assert refreshed.count(metro) == 2
    finally:
        queue_mod._BASELINE_LAST_ATTEMPT.pop(metro, None)
        await pg_pool.execute("delete from hunts where id = $1", hunt_id)
        await pg_pool.execute("delete from properties where id = $1", property_id)
        await _cleanup_metro(pg_pool, metro)
