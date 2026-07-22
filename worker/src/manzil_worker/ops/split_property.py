"""`split_property` — the unmerge admin operation (P3-4, DESIGN §10.3, §17 R5).

DEDUPE merges two URLs it believes name one building into a single Property so a
fact extracted once is shared by every Hunt that added that building. When a
merge is wrong, that sharing is a liability: a fact from building B now shows on
building A's row for everyone (R5). So the reversal ships the same day as the
merge — peel one Source off a merged Property onto a fresh Property row,
re-point everything that hung off that Source, and re-score every affected Hunt.

Posture: **admin-only, service-role.** This runs on `DATABASE_URL` like the
worker, entirely below the RLS boundary — there is no API surface and no
`auth.uid()` involved. The caller (the `manzil split-property` CLI verb) is the
gate; nothing user-facing reaches this function.

What moves, and what does not:

* `property_sources` — the one moved Source row (by id) → new Property.
* Source candidate `extractions` and their single-Source resolved rows → new
  Property. P3-6 extends this operation before multi-candidate resolutions can
  exist; P3-SC2 never leaves a cross-Property provenance edge.
* `floor_plans` where `source_id` = the moved Source → new Property.
* `hunt_listings` for the affected Listings → new Property (see below).
* `scores` are NOT touched: they key on `(hunt_listing_id, floor_plan_id)` and
  the moved floor plans keep their ids, so the rows stay valid and the enqueued
  rescore refreshes them.
* `property_images` whose `source_url` matches the moved Source → new Property.
  Pre-P3-7 rows have NULL `source_url` and remain on the original Property rather
  than being guessed at; the next IMAGE_FETCH re-derives them.

Geocode is deliberately dropped: the new Property gets NULL `place_id/lat/lng`
even though the original has them, because the split exists precisely because
that geocode may belong to the *other* building. The next ingest/refresh of the
moved Listing re-geocodes from freshly extracted identity.

Everything runs in one transaction: all validation happens before the first
write, and any failure rolls the whole split back — a half-split Property is
worse than an un-split one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from urllib.parse import urlsplit
from uuid import UUID

import asyncpg
from manzil_shared.errors import ManzilError

from manzil_worker.fetching.slug_hint import search_hint


class SplitError(ManzilError):
    """A `split_property` precondition was not met (unknown/foreign Source,
    single-source Property, or a Listing that is not on the Property). Raised
    before any write, so the transaction rolls back untouched."""


@dataclass(frozen=True)
class SplitResult:
    """Summary of a completed split, for the CLI to print."""

    new_property_id: UUID
    moved_source_id: UUID
    moved_listing_ids: list[UUID] = field(default_factory=list)
    rescored_hunt_ids: list[UUID] = field(default_factory=list)
    moved_extraction_count: int = 0
    moved_floor_plan_count: int = 0
    moved_image_count: int = 0


def _placeholder_name(url: str) -> str:
    """The submit-listing placeholder convention (api `_placeholder_name`):
    a titled URL-slug hint, falling back to the host. Honest about not knowing
    the real identity yet — the moved Listing's next run re-extracts it."""
    hint = search_hint(url)
    if hint:
        return hint.title()
    host = urlsplit(url).hostname
    return host or "Unknown listing"


def _rowcount(status: str) -> int:
    """asyncpg command status → affected-row count ('UPDATE 3' → 3)."""
    return int(status.split()[-1])


async def split_property(
    conn: asyncpg.Connection,
    *,
    property_id: UUID,
    source_url: str,
    listing_ids: list[UUID] | None = None,
) -> SplitResult:
    """Peel the Source at `source_url` off Property `property_id` onto a fresh
    Property, re-point its dependent rows and the affected Listings, and enqueue
    a rescore for every Hunt with a Listing on either side.

    `listing_ids`, when given, names exactly which Listings move (each must
    currently point at `property_id`, else `SplitError`). When omitted, the
    affected Listings are derived from the ingest jobs whose payload URL matches
    `source_url`. A derivation that finds none is not an error — the global-fact
    split is still valid; the caller is expected to surface a "0 listings moved"
    warning from an empty `moved_listing_ids`.

    Raises `SplitError` on any precondition failure (all checked before writing).
    """
    async with conn.transaction():
        # 1. The Source must exist and belong to this Property.
        source = await conn.fetchrow(
            "select id, property_id from property_sources where url = $1",
            source_url,
        )
        if source is None:
            raise SplitError(f"no property_source with url {source_url!r}")
        if source["property_id"] != property_id:
            raise SplitError(
                f"source {source_url!r} belongs to property {source['property_id']}, "
                f"not {property_id} — refusing to split"
            )
        source_id: UUID = source["id"]

        # A single-source Property has nothing to split: peeling its only Source
        # would leave an empty husk. Re-merge (not split) is the tool for that.
        source_count = await conn.fetchval(
            "select count(*) from property_sources where property_id = $1",
            property_id,
        )
        if source_count < 2:
            raise SplitError(
                f"property {property_id} has only {source_count} source — a split "
                "needs at least two (nothing would remain on the original)"
            )

        # 2. Resolve the affected Listings BEFORE re-pointing anything.
        if listing_ids is not None:
            rows = await conn.fetch(
                "select id from hunt_listings where id = any($1::uuid[]) and property_id = $2",
                listing_ids,
                property_id,
            )
            on_property = {r["id"] for r in rows}
            not_on_property = [lid for lid in listing_ids if lid not in on_property]
            if not_on_property:
                raise SplitError(
                    f"listings not on property {property_id}: "
                    f"{', '.join(str(lid) for lid in not_on_property)}"
                )
            affected_listing_ids = list(dict.fromkeys(listing_ids))
        else:
            # Derive from the ingest jobs that carried this URL (distinct listing).
            rows = await conn.fetch(
                """
                select distinct hl.id
                from hunt_listings hl
                join jobs j on j.hunt_listing_id = hl.id
                where hl.property_id = $1 and j.payload ->> 'url' = $2
                """,
                property_id,
                source_url,
            )
            affected_listing_ids = [r["id"] for r in rows]

        # 3. New Property with the placeholder identity; geocode deliberately null.
        placeholder = _placeholder_name(source_url)
        new_property_id: UUID = await conn.fetchval(
            "insert into properties (name, canonical_address) values ($1, $1) returning id",
            placeholder,
        )

        # 4. Re-point the Source and its provenance.
        await conn.execute(
            "update property_sources set property_id = $1 where id = $2",
            new_property_id,
            source_id,
        )
        # P3-SC2 currently writes one candidate + one single_source resolution.
        # Resolve the companion rows before moving either side. A mixed-source
        # graph is impossible until P3-6, which owns extending this split path
        # alongside the reconciliation ladder.
        mixed_resolution = await conn.fetchval(
            """
            select exists (
                select 1
                from extraction_resolution_candidates moved_edge
                join extractions moved on moved.id = moved_edge.candidate_extraction_id
                where moved.source_id = $1
                  and exists (
                      select 1
                      from extraction_resolution_candidates other_edge
                      join extractions other on other.id = other_edge.candidate_extraction_id
                      where other_edge.resolution_extraction_id =
                            moved_edge.resolution_extraction_id
                        and other.source_id is distinct from $1
                  )
            )
            """,
            source_id,
        )
        if mixed_resolution:
            raise SplitError(
                "split encountered a multi-Source resolution graph; P3-6 reconciliation "
                "must recompute both sides before this split can proceed"
            )
        resolution_ids = await conn.fetch(
            """
            select distinct erc.resolution_extraction_id as id
            from extraction_resolution_candidates erc
            join extractions candidate on candidate.id = erc.candidate_extraction_id
            where candidate.source_id = $1
            """,
            source_id,
        )
        ext_status = await conn.execute(
            "update extractions set property_id = $1 where source_id = $2",
            new_property_id,
            source_id,
        )
        resolution_status = await conn.execute(
            "update extractions set property_id = $1 where id = any($2::uuid[])",
            new_property_id,
            [row["id"] for row in resolution_ids],
        )
        fp_status = await conn.execute(
            "update floor_plans set property_id = $1 where source_id = $2",
            new_property_id,
            source_id,
        )
        image_status = await conn.execute(
            "update property_images set property_id = $1 where property_id = $2 "
            "and source_url = $3",
            new_property_id,
            property_id,
            source_url,
        )

        # 5. Re-point the affected Listings (scores ride along on floor_plan ids).
        if affected_listing_ids:
            await conn.execute(
                "update hunt_listings set property_id = $1 where id = any($2::uuid[])",
                new_property_id,
                affected_listing_ids,
            )

        # 6. Rescore every Hunt with a Listing on EITHER side — both the original
        #    and the new Property may score differently now. Read after re-pointing
        #    so the moved Listings count toward the new Property.
        hunt_rows = await conn.fetch(
            "select distinct hunt_id from hunt_listings where property_id = any($1::uuid[])",
            [property_id, new_property_id],
        )
        rescored_hunt_ids = [r["hunt_id"] for r in hunt_rows]
        for hunt_id in rescored_hunt_ids:
            await conn.execute(
                """
                insert into jobs (hunt_id, type, state, payload)
                values ($1, 'rescore', 'queued', $2::jsonb)
                """,
                hunt_id,
                json.dumps({"hunt_id": str(hunt_id)}),
            )

    return SplitResult(
        new_property_id=new_property_id,
        moved_source_id=source_id,
        moved_listing_ids=affected_listing_ids,
        rescored_hunt_ids=rescored_hunt_ids,
        moved_extraction_count=_rowcount(ext_status) + _rowcount(resolution_status),
        moved_floor_plan_count=_rowcount(fp_status),
        moved_image_count=_rowcount(image_status),
    )
