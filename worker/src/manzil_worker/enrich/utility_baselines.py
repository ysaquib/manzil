"""Utility-baselines job (P3-9, DESIGN §9.5, §14, §20 2026-07-23).

Regional utility estimates behind the §9.5 composition: for each due baseline
region with an active listing, one forced-schema LLM pass emits winter-weighted
`monthly_high` and typical `monthly_median` figures per utility per beds
bucket, upserted into `utility_baselines` on a 180-day TTL.

NOT a `jobs` row: `jobs.hunt_id` is NOT NULL and this is global, hunt-less
maintenance — the worker's scheduler tick (queue.py) spawns it directly as a
guarded asyncio task, one per due region, behind a Postgres advisory lock.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import structlog
from manzil_shared.config import UTILITY_BASELINE_TTL_DAYS
from pydantic import BaseModel, Field

from manzil_worker.llm import client as llm_client

log = structlog.get_logger()

BASELINE_UTILITIES = ("electric", "electric_heat", "gas_heat", "water", "sewer", "trash")
BEDS_BUCKETS = (0, 1, 2, 3)
EXPECTED_ROW_COUNT = len(BEDS_BUCKETS) * len(BASELINE_UTILITIES)

GeoLevel = Literal["city", "county", "state"]


@dataclass(frozen=True)
class BaselineRegion:
    geo_level: GeoLevel
    state: str
    region_name: str

    def lock_key(self) -> str:
        return f"utility_baselines:{self.geo_level}:{self.state}:{self.region_name}"


@dataclass(frozen=True)
class BaselineSet:
    region: BaselineRegion
    values: dict[str, tuple[float, float]]


class BaselineRowOut(BaseModel):
    utility: Literal["electric", "electric_heat", "gas_heat", "water", "sewer", "trash"]
    beds_bucket: int = Field(ge=0, le=3)
    monthly_high: float = Field(gt=0, description="Winter-weighted peak-month dollars.")
    monthly_median: float = Field(gt=0, description="Typical-month dollars.")


class RegionBaselinesOut(BaseModel):
    """Forced schema for one regional pass: every (beds_bucket x utility) combo."""

    rows: list[BaselineRowOut]
    sources: list[str] = Field(
        default_factory=list,
        description="Utility providers / rate sources the figures are based on.",
    )


def select_baseline_region(
    *,
    city: str | None,
    state: str | None,
    county: str | None,
) -> BaselineRegion | None:
    """Approved scope selection — not a cascading fallback."""
    if state is None:
        return None
    if city:
        return BaselineRegion(geo_level="city", state=state, region_name=city)
    if county:
        return BaselineRegion(geo_level="county", state=state, region_name=county)
    return BaselineRegion(geo_level="state", state=state, region_name=state)


def region_scope_label(region: BaselineRegion) -> str:
    if region.geo_level == "city":
        return f"City: {region.region_name}, State: {region.state}, USA"
    if region.geo_level == "county":
        return f"County: {region.region_name}, State: {region.state}, USA"
    return f"State: {region.state}, USA"


def region_estimate_note(region: BaselineRegion) -> str | None:
    if region.geo_level == "city":
        return None
    if region.geo_level == "county":
        return f"{region.region_name}, {region.state} regional estimate"
    return f"{region.state} regional estimate"


async def due_baseline_regions(
    conn: Any, *, ttl_days: int = UTILITY_BASELINE_TTL_DAYS
) -> list[BaselineRegion]:
    """Regions for active listings whose baseline set is absent or stale."""
    cutoff = datetime.now(UTC) - timedelta(days=ttl_days)
    rows = await conn.fetch(
        """
        select distinct p.city, p.state, p.county
        from properties p
        join hunt_listings hl on hl.property_id = p.id
        where hl.status = 'active' and p.state is not null
        """,
    )
    candidates: dict[tuple[str, str, str], BaselineRegion] = {}
    for row in rows:
        region = select_baseline_region(city=row["city"], state=row["state"], county=row["county"])
        if region is None:
            continue
        candidates[(region.geo_level, region.state, region.region_name)] = region

    due: list[BaselineRegion] = []
    for region in sorted(
        candidates.values(),
        key=lambda r: (r.geo_level, r.state, r.region_name),
    ):
        count = await conn.fetchval(
            """
            select count(*)::int from utility_baselines
            where geo_level = $1 and state = $2 and region_name = $3
              and refreshed_at >= $4
            """,
            region.geo_level,
            region.state,
            region.region_name,
            cutoff,
        )
        if count < EXPECTED_ROW_COUNT:
            due.append(region)
    return due


async def _example_address(conn: Any, region: BaselineRegion) -> str | None:
    """One canonical address in the region — useful LLM context."""
    if region.geo_level == "city":
        return await conn.fetchval(
            """
            select p.canonical_address
            from properties p join hunt_listings hl on hl.property_id = p.id
            where hl.status = 'active'
              and p.city = $1 and p.state = $2
              and p.canonical_address is not null
            limit 1
            """,
            region.region_name,
            region.state,
        )
    if region.geo_level == "county":
        return await conn.fetchval(
            """
            select p.canonical_address
            from properties p join hunt_listings hl on hl.property_id = p.id
            where hl.status = 'active'
              and p.city is null and p.county = $1 and p.state = $2
              and p.canonical_address is not null
            limit 1
            """,
            region.region_name,
            region.state,
        )
    return await conn.fetchval(
        """
        select p.canonical_address
        from properties p join hunt_listings hl on hl.property_id = p.id
        where hl.status = 'active'
          and p.city is null and p.county is null and p.state = $1
          and p.canonical_address is not null
        limit 1
        """,
        region.state,
    )


async def refresh_region_baselines(
    conn: Any,
    region: BaselineRegion,
    *,
    call_structured: Any = None,
) -> int:
    """One regional pass: structured call → validate full coverage → upsert."""
    call = call_structured or llm_client.call_structured
    address = await _example_address(conn, region)
    content = region_scope_label(region)
    if address:
        content += f"\nExample property address in this region: {address}"

    out: RegionBaselinesOut = await call("utility_baselines", RegionBaselinesOut, content)

    by_key = {(row.beds_bucket, row.utility): row for row in out.rows}
    missing = [
        (bucket, utility)
        for bucket in BEDS_BUCKETS
        for utility in BASELINE_UTILITIES
        if (bucket, utility) not in by_key
    ]
    if missing:
        raise ValueError(
            f"utility_baselines[{region.lock_key()}]: incomplete coverage — missing {missing[:6]}"
            f"{'…' if len(missing) > 6 else ''}; nothing written"
        )

    sources = json.dumps({"search": False, "claimed": out.sources})
    written = 0
    for (bucket, utility), row in sorted(by_key.items()):
        high = max(row.monthly_high, row.monthly_median)
        await conn.execute(
            """
            insert into utility_baselines
                (geo_level, state, region_name, beds_bucket, utility,
                 monthly_high, monthly_median, sources, refreshed_at)
            values ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, now())
            on conflict (geo_level, state, region_name, beds_bucket, utility) do update set
                monthly_high = excluded.monthly_high,
                monthly_median = excluded.monthly_median,
                sources = excluded.sources,
                refreshed_at = now()
            """,
            region.geo_level,
            region.state,
            region.region_name,
            bucket,
            utility,
            round(high, 2),
            round(row.monthly_median, 2),
            sources,
        )
        written += 1
    log.info(
        "utility_baselines_refreshed",
        geo_level=region.geo_level,
        state=region.state,
        region_name=region.region_name,
        rows=written,
    )
    return written


async def baselines_for_region(
    conn: Any, region: BaselineRegion, bucket: int
) -> BaselineSet | None:
    """Composition input for one region + beds bucket, or None when no rows."""
    rows = await conn.fetch(
        """
        select utility, monthly_high, monthly_median from utility_baselines
        where geo_level = $1 and state = $2 and region_name = $3 and beds_bucket = $4
        """,
        region.geo_level,
        region.state,
        region.region_name,
        bucket,
    )
    if not rows:
        return None
    return BaselineSet(
        region=region,
        values={
            row["utility"]: (float(row["monthly_high"]), float(row["monthly_median"]))
            for row in rows
        },
    )


async def baselines_for_property_locality(
    conn: Any,
    *,
    city: str | None,
    state: str | None,
    county: str | None,
    bucket: int,
) -> BaselineSet | None:
    region = select_baseline_region(city=city, state=state, county=county)
    if region is None:
        return None
    return await baselines_for_region(conn, region, bucket)
