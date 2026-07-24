"""Backfill locality columns on existing Properties (DESIGN §8.2, §20 2026-07-23).

`geocode_property`'s forever-cache contract is unchanged — this command explicitly
re-geocodes Properties missing any locality field and coalesces the results.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import structlog

from manzil_worker.enrich.maps import MapsError, _geocode_call

log = structlog.get_logger()


@dataclass(frozen=True)
class BackfillLocalityResult:
    attempted: int
    updated: int
    failed: int


async def backfill_locality(
    conn: Any,
    *,
    property_ids: list[UUID] | None = None,
    geocode_call: Any = None,
) -> BackfillLocalityResult:
    """Geocode Properties missing city/state/county and persist with coalesce."""
    geocode = geocode_call or _geocode_call
    if property_ids:
        rows = await conn.fetch(
            """
            select id, canonical_address, place_id, lat, lng, city, state, county
            from properties
            where id = any($1::uuid[])
              and (city is null or state is null or county is null)
            order by id
            """,
            property_ids,
        )
    else:
        rows = await conn.fetch(
            """
            select id, canonical_address, place_id, lat, lng, city, state, county
            from properties
            where city is null or state is null or county is null
            order by id
            """
        )

    attempted = len(rows)
    updated = 0
    failed = 0
    for row in rows:
        address = row["canonical_address"]
        if not address:
            failed += 1
            log.warning(
                "backfill_locality_skipped",
                property_id=str(row["id"]),
                reason="no_address",
            )
            continue
        try:
            result = await geocode(address)
        except MapsError as error:
            failed += 1
            log.warning(
                "backfill_locality_failed",
                property_id=str(row["id"]),
                error=str(error),
            )
            continue
        await conn.execute(
            """
            update properties set
                place_id = coalesce(place_id, $2),
                lat = coalesce(lat, $3),
                lng = coalesce(lng, $4),
                city = coalesce(city, $5),
                state = coalesce(state, $6),
                county = coalesce(county, $7)
            where id = $1
            """,
            row["id"],
            result["place_id"],
            result["lat"],
            result["lng"],
            result.get("city"),
            result.get("state"),
            result.get("county"),
        )
        updated += 1
    return BackfillLocalityResult(attempted=attempted, updated=updated, failed=failed)
