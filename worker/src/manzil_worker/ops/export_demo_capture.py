"""Export a Replay Capture from a real ingest Job (DM-9, DESIGN §3, §16).

A **Replay Capture** is a recording of a run that really happened: the
`job_events` timeline plus the finished read payload, exported once and replayed
in the visitor's browser. When a Demo Account submits a URL, nothing is fetched,
no Job is enqueued and no row is written -- the bundle is played back into the
query cache instead. That is what makes "a demo writes nothing" literally true
rather than nearly true: running the real pipeline in replay mode would still
write eight tables and need a purge path.

Every value in the bundle was extracted from a real page. The one thing that is
**not** faithful is the clock: playback compresses a three-to-five minute run
into well under a minute (DESIGN §20 v3.57). Real per-stage durations travel in
the bundle so the UI can keep showing what the run actually cost in time; only
the pacing of the animation is synthetic, and the disclosure says so.

Deliberately not exported: anything about a person. Comments, ratings and
member display names are Hunt collaboration content, not pipeline output, and
the finished payload here is the Listing as the pipeline produced it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg

CAPTURE_VERSION = 1

# job_events.detail can carry stage payloads that are large (plan manifests) or
# simply uninteresting to a viewer. Keys worth keeping are the ones the Tasks UI
# actually reads for a non-checkpoint event.
_DETAIL_KEYS = {
    "tier",
    "url",
    "source_url",
    "reason",
    "code",
    "message",
    "count",
    "stage_index",
    "cost_usd",
}
# Deliberately absent, and each for a reason a future contributor must not undo
# by "restoring" it:
#   `prompt` / `question` -- a checkpoint's question interpolates `flag.note`,
#       which can carry a verbatim page excerpt (stages/verify.py's evidence
#       check) or model prose derived from the page (its consistency check).
#       The replay animates through checkpoints as ordinary timeline beats
#       rather than rendering a prompt, so none of it is needed (DESIGN §20
#       v3.58 -- checkpoint rendering was cut from DM-9's scope for exactly
#       this reason).
#   `answer` -- `checkpoint_answered` detail carries the member's free-typed
#       text for the §10.10 `other:` form.
#   `choice` -- only meaningful alongside a prompt that is no longer exported.
#   `result` -- the `fetch_page` tool event stores a 2 kB raw page prefix.


class CaptureError(RuntimeError):
    """The chosen Job cannot produce an honest capture."""


@dataclass
class CaptureEvent:
    offset_ms: int
    stage: str
    event: str
    detail: dict[str, Any] = field(default_factory=dict)


def _prune_detail(detail: Any) -> dict[str, Any]:
    if not isinstance(detail, dict):
        return {}
    return {k: v for k, v in detail.items() if k in _DETAIL_KEYS}


def _offsets(rows: list[asyncpg.Record]) -> list[CaptureEvent]:
    """Events as milliseconds since the first one, with detail pruned."""
    first: datetime = rows[0]["at"]
    return [
        CaptureEvent(
            offset_ms=int((row["at"] - first).total_seconds() * 1000),
            stage=row["stage"],
            event=row["event"],
            detail=_prune_detail(row["detail"]),
        )
        for row in rows
    ]


async def export_demo_capture(conn: asyncpg.Connection, job_id: UUID) -> dict[str, Any]:
    """Build the capture bundle for `job_id`.

    Raises `CaptureError` rather than emitting a bundle that would replay into a
    misleading demo -- an unfinished run, or one with no timeline to animate.

    Deliberately does not require or reject a checkpoint. Reconstructing a
    renderable, honestly-scoped prompt turned out to need either widening
    `checkpoint_asked` to carry the full §10.10 shape (which a security review
    showed could publish page excerpts and model-authored prose if this legacy
    export were copied into a public frontend build) or a
    per-checkpoint-kind allow-list keyed to the originating flag's `check` --
    real work, deferred (DESIGN §20 v3.58). Any recorded checkpoint events
    still replay, just as ordinary timeline beats: `capture.ts` treats
    `checkpoint_asked`/`checkpoint_answered`/`checkpoint_auto_resolved` as
    `completed`-shaped for state derivation, so the run animates straight
    through rather than parking with a prompt nobody can render.
    """
    job = await conn.fetchrow(
        """
        select j.id, j.hunt_id, j.hunt_listing_id, j.type, j.state, j.current_stage,
               j.plan, j.payload, j.attempts, j.cost_actual_usd, j.created_at,
               j.started_at, j.finished_at, j.warnings,
               hl.source_policy, ps.url, p.name as property_name
          from jobs j
          left join hunt_listings hl on hl.id = j.hunt_listing_id
          left join properties p on p.id = hl.property_id
          left join property_sources ps on ps.id = hl.submitted_source_id
         where j.id = $1
        """,
        job_id,
    )
    if job is None:
        raise CaptureError(f"No Job {job_id}")
    if job["state"] != "done":
        raise CaptureError(
            f"Job {job_id} is {job['state']}. A Replay Capture is a recording of a "
            "run that finished; exporting anything else would animate a demo into "
            "a state the real run never reached."
        )

    event_rows = await conn.fetch(
        "select stage, event, detail, at from job_events where job_id = $1 order by at, ctid",
        job_id,
    )
    if len(event_rows) < 2:
        raise CaptureError(
            f"Job {job_id} has {len(event_rows)} events; there is no timeline to replay."
        )

    events = _offsets(list(event_rows))
    has_checkpoint = any(e.event.startswith("checkpoint_") for e in events)

    listing = await _listing_payload(conn, job["hunt_listing_id"])

    return {
        "version": CAPTURE_VERSION,
        "exported_at": datetime.now().astimezone().isoformat(),
        "source": {
            "job_id": str(job["id"]),
            "url": job["url"],
            "property_name": job["property_name"],
            "source_policy": job["source_policy"],
        },
        "job": {
            "type": job["type"],
            "cost_actual_usd": float(job["cost_actual_usd"] or 0),
            "attempts": job["attempts"],
            "plan": _json(job["plan"]),
            "warnings": _json(job["warnings"]) or [],
            # The real wall-clock duration. Playback is faster than this on
            # purpose; keeping the true figure means the UI never has to invent
            # one, and the disclosure can be specific about the compression.
            "real_duration_ms": _duration_ms(job["started_at"], job["finished_at"]),
        },
        "events": [
            {
                "offset_ms": e.offset_ms,
                "stage": e.stage,
                "event": e.event,
                "detail": e.detail,
            }
            for e in events
        ],
        "has_checkpoint": has_checkpoint,
        "listing": listing,
    }


def _duration_ms(started: datetime | None, finished: datetime | None) -> int | None:
    if started is None or finished is None:
        return None
    return int((finished - started).total_seconds() * 1000)


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else value


def _num(value: Any) -> float | None:
    return float(value) if value is not None else None


async def _listing_payload(conn: asyncpg.Connection, listing_id: UUID | None) -> dict[str, Any]:
    """The finished Listing exactly as `useListings`' embed produces it.

    Shaped by what the frontend needs rather than by a table: the replay ends by
    putting this row into the `hunt_listings` query cache, so the visitor sees
    the Listing they just "submitted" appear with a real score. Getting the
    shape wrong throws on arrival -- `unitGroups.ts` iterates
    `property.floor_plans` unguarded -- so this mirrors
    `frontend/src/features/listings/types.ts`'s `Listing`/`Property`/
    `FloorPlan`/`PropertySource`/`Score` field-for-field.

    Every query below names its columns. Never `select *`: this runs
    service-role on a direct pool, where `select ps.*` on `property_sources`
    returns `cleaned_text` -- the column that is revoked from every
    authenticated member precisely so page bodies are not published, and this
    legacy bundle was historically copied into a world-readable frontend build.
    The supported v3.72 runtime stores sanitized captures privately and serves
    only the current release through authenticated API routes, but this exporter
    remains conservative because its output can still be mishandled manually.
    """
    if listing_id is None:
        raise CaptureError("The Job has no Listing; there is nothing to show at the end.")

    row = await conn.fetchrow(
        """
        select hl.id, hl.hunt_id, hl.property_id, hl.status, hl.source_policy,
               hl.single_source_reason, hl.pins, hl.created_at, hl.unavailable_at,
               hl.all_in_components, hl.move_in_components,
               p.name, p.canonical_address, p.city, p.state, p.county,
               p.official_url, p.lat, p.lng
          from hunt_listings hl
          join properties p on p.id = hl.property_id
         where hl.id = $1
        """,
        listing_id,
    )
    if row is None:
        raise CaptureError(f"Listing {listing_id} no longer exists.")

    # `added_by` is deliberately not selected: a member's auth uid is not
    # pipeline output, and DESIGN §3's "a recording" rule does not compel
    # publishing who submitted the URL.

    plans = await conn.fetch(
        """
        select id, property_id, source_id, plan_name, beds, baths, unit_types,
               sqft_min, sqft_max, rent_min, rent_max, deposit, availability_date,
               available_units, is_current, source_native_id, detail_url
          from floor_plans
         where property_id = $1 and is_current
         order by beds, plan_name
        """,
        row["property_id"],
    )

    sources = await conn.fetch(
        """
        select id, property_id, url, site_domain, is_official,
               last_fetched_at, last_success_at
          from property_sources
         where property_id = $1
         order by is_official desc, url
        """,
        row["property_id"],
    )

    # Scores are per Floor Plan (§9.3), so the capture carries them that way and
    # lets the Overview roll them up exactly as it does for a real Listing.
    scores = await conn.fetch(
        """
        select hunt_listing_id, floor_plan_id, total, breakdown, rubric_version,
               computed_at, all_in_components, move_in_components
          from scores where hunt_listing_id = $1
        """,
        listing_id,
    )

    return {
        "id": str(row["id"]),
        "hunt_id": str(row["hunt_id"]),
        "property_id": str(row["property_id"]),
        "status": row["status"],
        "source_policy": row["source_policy"],
        "single_source_reason": row["single_source_reason"],
        "pins": _json(row["pins"]) or {},
        "created_at": _iso(row["created_at"]),
        "unavailable_at": _iso(row["unavailable_at"]),
        "all_in_components": _json(row["all_in_components"]),
        "move_in_components": _json(row["move_in_components"]),
        "property": {
            "id": str(row["property_id"]),
            "name": row["name"],
            "canonical_address": row["canonical_address"],
            "city": row["city"],
            "state": row["state"],
            "county": row["county"],
            "official_url": row["official_url"],
            "lat": _num(row["lat"]),
            "lng": _num(row["lng"]),
            "floor_plans": [
                {
                    "id": str(fp["id"]),
                    "property_id": str(fp["property_id"]),
                    "source_id": str(fp["source_id"]) if fp["source_id"] else None,
                    "plan_name": fp["plan_name"],
                    "beds": _num(fp["beds"]),
                    "baths": _num(fp["baths"]),
                    "unit_types": _json(fp["unit_types"]),
                    "sqft_min": fp["sqft_min"],
                    "sqft_max": fp["sqft_max"],
                    "rent_min": _num(fp["rent_min"]),
                    "rent_max": _num(fp["rent_max"]),
                    "deposit": _num(fp["deposit"]),
                    "availability_date": _iso(fp["availability_date"]),
                    "available_units": fp["available_units"],
                    "is_current": fp["is_current"],
                    "source_native_id": fp["source_native_id"],
                    "detail_url": fp["detail_url"],
                }
                for fp in plans
            ],
            "sources": [
                {
                    "id": str(src["id"]),
                    "property_id": str(src["property_id"]),
                    "url": src["url"],
                    "site_domain": src["site_domain"],
                    "is_official": src["is_official"],
                    "last_fetched_at": _iso(src["last_fetched_at"]),
                    "last_success_at": _iso(src["last_success_at"]),
                }
                for src in sources
            ],
        },
        "scores": [
            {
                "hunt_listing_id": str(sc["hunt_listing_id"]),
                "floor_plan_id": str(sc["floor_plan_id"]) if sc["floor_plan_id"] else None,
                "total": _num(sc["total"]),
                "breakdown": _json(sc["breakdown"]),
                "rubric_version": sc["rubric_version"],
                "computed_at": _iso(sc["computed_at"]),
                "all_in_components": _json(sc["all_in_components"]),
                "move_in_components": _json(sc["move_in_components"]),
            }
            for sc in scores
        ],
    }
