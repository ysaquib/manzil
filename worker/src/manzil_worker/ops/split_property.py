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
  Property. A mixed P3-6 resolution is detached and freshly resolved on both
  sides; P3-SC2 never leaves a cross-Property provenance edge.
* `floor_plans` where `source_id` = the moved Source → new Property.
* `hunt_listings` for the affected Listings → new Property (see below).
* `scores` are NOT touched: they key on `(hunt_listing_id, floor_plan_id)` and
  the moved floor plans keep their ids, so the rows stay valid and the enqueued
  rescore refreshes them.
* `property_images` whose `source_url` matches the moved Source → new Property.
  Pre-P3-7 rows have NULL `source_url` and remain on the original Property rather
  than being guessed at; the next IMAGE_FETCH re-derives them.

Geocode is deliberately dropped: the new Property gets NULL `place_id/lat/lng`
and NULL locality (`city/state/county`) even though the original has them,
because the split exists precisely because that geocode may belong to the
*other* building. The next ingest/refresh of the moved Listing re-geocodes
from freshly extracted identity.

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
from manzil_shared.models import Confidence, TargetScope, UnitApplicability

from manzil_worker.fetching.slug_hint import search_hint
from manzil_worker.scoped_facts import append_resolution
from manzil_worker.state import SourceClaim


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


def _json_value(raw: object) -> object:
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


_CONFIDENCE_RANK = {
    Confidence.HIGH.value: 3,
    Confidence.MEDIUM.value: 2,
    Confidence.LOW.value: 1,
    Confidence.NOT_FOUND.value: 0,
}


async def _append_split_resolution(
    conn: asyncpg.Connection,
    *,
    property_id: UUID,
    resolution: asyncpg.Record,
    candidates: list[asyncpg.Record],
) -> None:
    """Re-resolve one side of a mixed provenance graph after a split.

    Prefer the previously selected candidate when it remains on that side;
    otherwise choose confidence then freshness deterministically. The queued
    rescore/next ingest can subsequently run the full reconciliation ladder.
    """
    selected = max(
        candidates,
        key=lambda row: (
            bool(row["selected"]),
            _CONFIDENCE_RANK[row["confidence"]],
            row["extracted_at"],
            str(row["candidate_id"]),
        ),
    )
    values = {
        json.dumps(_json_value(row["value"]), sort_keys=True, default=str) for row in candidates
    }
    target_scope = TargetScope(resolution["target_scope"])
    applicability = (
        UnitApplicability(resolution["applicability"])
        if resolution["applicability"] is not None
        else None
    )
    candidate_ids: dict[UUID, list[tuple[TargetScope, UUID | None, UUID]]] = {}
    group_ids: list[UUID] = []
    for row in candidates:
        group_id = row["claim_group_id"]
        if group_id not in candidate_ids:
            group_ids.append(group_id)
        candidate_ids.setdefault(group_id, []).append(
            (target_scope, resolution["floor_plan_id"], row["candidate_id"])
        )
    claim = SourceClaim(
        criterion_key=resolution["criterion_key"],
        value=_json_value(selected["value"]),
        confidence=Confidence(selected["confidence"]),
        evidence_quote=selected["evidence_quote"],
        model=selected["model"],
        prompt_version=0,
        target_scope=target_scope,
        floor_plan_id=resolution["floor_plan_id"],
        applicability=applicability,
        claim_group_id=selected["claim_group_id"],
        resolution_rule="split_recompute",
        disputed=len(values) > 1,
        candidate_claim_group_ids=group_ids,
    )
    await append_resolution(
        conn,
        property_id=property_id,
        hunt_id=resolution["hunt_id"],
        claim=claim,
        floor_plan_id=resolution["floor_plan_id"],
        model=selected["model"],
        job_id=None,
        candidate_ids=candidate_ids,
    )


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

        # 4. Capture the provenance graph before moving either side. Mixed
        # P3-6 resolutions are split into two fresh resolutions below.
        mixed_resolution_rows = await conn.fetch(
            """
            select distinct resolved.*
            from extraction_resolution_candidates moved_edge
            join extractions moved on moved.id = moved_edge.candidate_extraction_id
            join extractions resolved on resolved.id = moved_edge.resolution_extraction_id
            where moved.source_id = $1
              and exists (
                  select 1
                  from extraction_resolution_candidates other_edge
                  join extractions other on other.id = other_edge.candidate_extraction_id
                  where other_edge.resolution_extraction_id =
                        moved_edge.resolution_extraction_id
                    and other.source_id is distinct from $1
              )
            """,
            source_id,
        )
        mixed_resolution_ids = [row["id"] for row in mixed_resolution_rows]
        mixed_candidates: dict[UUID, list[asyncpg.Record]] = {}
        if mixed_resolution_ids:
            rows = await conn.fetch(
                """
                select edge.resolution_extraction_id, edge.selected,
                       candidate.id as candidate_id, candidate.source_id,
                       candidate.claim_group_id, candidate.value,
                       candidate.confidence, candidate.evidence_quote,
                       candidate.model, candidate.extracted_at
                from extraction_resolution_candidates edge
                join extractions candidate on candidate.id = edge.candidate_extraction_id
                where edge.resolution_extraction_id = any($1::uuid[])
                """,
                mixed_resolution_ids,
            )
            for row in rows:
                mixed_candidates.setdefault(row["resolution_extraction_id"], []).append(row)
            # The historical resolution stays with the original Property. Its
            # cross-Property edges must be detached before candidates move.
            await conn.execute(
                """
                delete from extraction_resolution_candidates edge
                using extractions candidate
                where edge.candidate_extraction_id = candidate.id
                  and edge.resolution_extraction_id = any($1::uuid[])
                  and candidate.source_id = $2
                """,
                mixed_resolution_ids,
                source_id,
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
        single_source_resolution_ids = [
            row["id"] for row in resolution_ids if row["id"] not in mixed_resolution_ids
        ]
        await conn.execute(
            "update property_sources set property_id = $1 where id = $2",
            new_property_id,
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
            single_source_resolution_ids,
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
        # Floor Plans move by `source_id` but images move by `source_url`, so a
        # diagram served from a different page of the moved Source would be left
        # behind while its plan departs — a cross-Property association the
        # `floor_plan_images` trigger forbids. The trigger fires on UPDATE as
        # well as INSERT, so a straddle cannot even be *recorded*; it has to be
        # prevented. Carry any image still associated with a moved plan across
        # with it. v1 associations are Source-local, so such an image can only
        # belong to the Source being split (§P3-SC5).
        await conn.execute(
            """
            update property_images set property_id = $1
            where property_id = $2
              and id in (
                  select c.property_image_id
                  from current_floor_plan_images c
                  join floor_plans fp on fp.id = c.floor_plan_id
                  where fp.property_id = $1
              )
            """,
            new_property_id,
            property_id,
        )
        for resolution in mixed_resolution_rows:
            candidates = mixed_candidates[resolution["id"]]
            old_side = [row for row in candidates if row["source_id"] != source_id]
            new_side = [row for row in candidates if row["source_id"] == source_id]
            if old_side:
                await _append_split_resolution(
                    conn,
                    property_id=property_id,
                    resolution=resolution,
                    candidates=old_side,
                )
            if new_side:
                moved_floor_plan_id = resolution["floor_plan_id"]
                if moved_floor_plan_id is not None and not await conn.fetchval(
                    "select property_id = $1 from floor_plans where id = $2",
                    new_property_id,
                    moved_floor_plan_id,
                ):
                    raise SplitError("mixed exact Floor Plan resolution crosses Source identity")
                await _append_split_resolution(
                    conn,
                    property_id=new_property_id,
                    resolution=resolution,
                    candidates=new_side,
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
