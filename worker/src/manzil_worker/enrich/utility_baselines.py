"""Utility-baselines job (P3-9, DESIGN §9.5, §14, §20 2026-07-18).

Metro-level utility estimates behind the §9.5 composition: for each metro with
an active listing, one forced-schema LLM pass emits winter-weighted
`monthly_high` and typical `monthly_median` figures per utility per beds
bucket, upserted into `utility_baselines` on a 120-day TTL.

NOT a `jobs` row: `jobs.hunt_id` is NOT NULL and this is global, hunt-less
maintenance — the worker's scheduler tick (queue.py) spawns it directly as a
guarded asyncio task, one per due metro, behind a Postgres advisory lock. If a
pass dies, the next tick retries; a 120-day cadence needs no queue durability.

Search interim (§20 2026-07-18): the pass is a plain structured call with no
live search until P3-5 lands the provider `web_search` plumbing — `sources`
records the model's claimed references marked `"search": false`. All-or-nothing
write: a pass that does not cover every (bucket x utility) combination is
rejected, because partial coverage would trip the composition's strict-unknown
branch on the gaps it left.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import structlog
from manzil_shared.config import UTILITY_BASELINE_TTL_DAYS
from pydantic import BaseModel, Field

from manzil_worker.llm import client as llm_client

log = structlog.get_logger()

# The vocabulary the composition reads (§9.5 heat rule): `electric` is the
# non-heating base; `electric_heat` is winter-weighted electric INCLUDING
# electric heating; `gas_heat` is winter-weighted heating gas.
BASELINE_UTILITIES = ("electric", "electric_heat", "gas_heat", "water", "sewer", "trash")
BEDS_BUCKETS = (0, 1, 2, 3)  # 3 = 3+ bedrooms


class BaselineRowOut(BaseModel):
    utility: Literal["electric", "electric_heat", "gas_heat", "water", "sewer", "trash"]
    beds_bucket: int = Field(ge=0, le=3)
    monthly_high: float = Field(gt=0, description="Winter-weighted peak-month dollars.")
    monthly_median: float = Field(gt=0, description="Typical-month dollars.")


class MetroBaselinesOut(BaseModel):
    """Forced schema for one metro pass: every (beds_bucket x utility) combo."""

    rows: list[BaselineRowOut]
    sources: list[str] = Field(
        default_factory=list,
        description="Utility providers / rate sources the figures are based on.",
    )


async def due_metros(conn: Any, *, ttl_days: int = UTILITY_BASELINE_TTL_DAYS) -> list[str]:
    """Metros (properties.city, §20 city-as-metro proxy) of active listings whose
    baselines are absent or older than the TTL."""
    cutoff = datetime.now(UTC) - timedelta(days=ttl_days)
    rows = await conn.fetch(
        """
        select metro from (
            select distinct p.city as metro
            from properties p
            join hunt_listings hl on hl.property_id = p.id
            where hl.status = 'active' and p.city is not null
        ) metros
        where not exists (
            select 1 from utility_baselines b
            where b.metro = metros.metro and b.refreshed_at >= $1
        )
        order by metro
        """,
        cutoff,
    )
    return [row["metro"] for row in rows]


async def _example_address(conn: Any, metro: str) -> str | None:
    """One canonical address in the metro — disambiguates same-named cities
    (Detroit MI vs Detroit OH) without storing state separately."""
    return await conn.fetchval(
        """
        select p.canonical_address
        from properties p join hunt_listings hl on hl.property_id = p.id
        where hl.status = 'active' and p.city = $1 and p.canonical_address is not null
        limit 1
        """,
        metro,
    )


async def refresh_metro_baselines(
    conn: Any,
    metro: str,
    *,
    call_structured: Any = None,
) -> int:
    """One metro pass: structured call → validate full coverage → upsert all
    rows. Returns the row count written. Raises on incomplete coverage or a
    failed call — the scheduler tick logs and retries next tick."""
    call = call_structured or llm_client.call_structured
    address = await _example_address(conn, metro)
    content = f"City / metro area: {metro}, USA"
    if address:
        content += f"\nExample property address in this metro: {address}"

    out: MetroBaselinesOut = await call("utility_baselines", MetroBaselinesOut, content)

    by_key = {(row.beds_bucket, row.utility): row for row in out.rows}
    missing = [
        (bucket, utility)
        for bucket in BEDS_BUCKETS
        for utility in BASELINE_UTILITIES
        if (bucket, utility) not in by_key
    ]
    if missing:
        raise ValueError(
            f"utility_baselines[{metro}]: incomplete coverage — missing {missing[:6]}"
            f"{'…' if len(missing) > 6 else ''}; nothing written"
        )

    # `sources` records the no-search interim honestly (§20 2026-07-18).
    sources = json.dumps({"search": False, "claimed": out.sources})
    written = 0
    for (bucket, utility), row in sorted(by_key.items()):
        # The winter-weighted high can never sit below the median.
        high = max(row.monthly_high, row.monthly_median)
        await conn.execute(
            """
            insert into utility_baselines
                (metro, beds_bucket, utility, monthly_high, monthly_median,
                 sources, refreshed_at)
            values ($1, $2, $3, $4, $5, $6::jsonb, now())
            on conflict (metro, beds_bucket, utility) do update set
                monthly_high = excluded.monthly_high,
                monthly_median = excluded.monthly_median,
                sources = excluded.sources,
                refreshed_at = now()
            """,
            metro,
            bucket,
            utility,
            round(high, 2),
            round(row.monthly_median, 2),
            sources,
        )
        written += 1
    log.info("utility_baselines_refreshed", metro=metro, rows=written)
    return written


async def baselines_for_metro(
    conn: Any, metro: str, bucket: int
) -> dict[str, tuple[float, float]] | None:
    """Composition input: utility → (monthly_high, monthly_median) for one
    metro + beds bucket, or None when the metro has no baseline rows at all
    (the composer's graceful v1 fallback branch)."""
    rows = await conn.fetch(
        """
        select utility, monthly_high, monthly_median from utility_baselines
        where metro = $1 and beds_bucket = $2
        """,
        metro,
        bucket,
    )
    if not rows:
        return None
    return {
        row["utility"]: (float(row["monthly_high"]), float(row["monthly_median"]))
        for row in rows
    }
