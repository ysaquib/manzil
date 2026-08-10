"""Durable Demo Hunt publication builder (DESIGN §20 v3.72).

The selected Hunt stays ordinary and live.  This module materialises only the
two things a public visitor must never generate: sanitized Replay Captures and
Google Static Maps stills.  Promotion is atomic; a failed or stale build leaves
the previous release serving unchanged.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import math
import os
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

import asyncpg
import httpx
import structlog
from manzil_shared.config import JOB_ORPHAN_AFTER_SECONDS
from PIL import Image, UnidentifiedImageError

from manzil_worker.enrich.images import SupabaseImageStore
from manzil_worker.ops.export_demo_capture import CaptureError, export_demo_capture

log = structlog.get_logger()

MAX_REPLAY_CAPTURES = 50
MAX_CAPTURE_BYTES = 1024 * 1024
MAX_MAPPED_PROPERTIES = 100
STATIC_MAPS = "https://maps.googleapis.com/maps/api/staticmap"
SCALE = 2
TILE = 256
DRAWER_SIZE = (640, 260)
HUNT_SIZE = (640, 400)
DRAWER_ZOOM = 15
HUNT_PADDING_PX = 64
PUBLICATION_ORPHAN_AFTER_SECONDS = JOB_ORPHAN_AFTER_SECONDS
PUBLICATION_HEARTBEAT_SECONDS = max(5, min(30, PUBLICATION_ORPHAN_AFTER_SECONDS // 3))

DARK_STYLE = [
    "element:geometry|color:0x262320",
    "element:labels.text.fill|color:0x8B867E",
    "element:labels.text.stroke|color:0x161412",
    "feature:administrative|element:geometry|color:0x48443E",
    "feature:poi|visibility:off",
    "feature:park|element:geometry|color:0x302C27",
    "feature:road|element:geometry|color:0x3D3933",
    "feature:road|element:labels.text.fill|color:0x8B867E",
    "feature:road.highway|element:geometry|color:0x48443E",
    "feature:transit|visibility:off",
    "feature:water|element:geometry|color:0x201D1A",
]
LIGHT_STYLE = [
    "feature:poi.business|visibility:off",
    "feature:transit|element:labels.icon|visibility:off",
]


@dataclass(frozen=True)
class DemoPlace:
    property_id: UUID
    name: str
    lat: float
    lng: float


@dataclass(frozen=True)
class DemoCapture:
    listing_id: UUID
    job_id: UUID
    payload: dict[str, Any]
    payload_bytes: int
    fingerprint: str


@dataclass(frozen=True)
class DemoSnapshot:
    hunt_id: UUID
    fingerprint: str
    active_count: int
    archived_count: int
    captures: list[DemoCapture]
    places: list[DemoPlace]
    blockers: list[str]
    warnings: list[str]


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


async def build_demo_snapshot(conn: asyncpg.Connection, hunt_id: UUID) -> DemoSnapshot:
    """Build the exact replay/map input and its canonical fingerprint."""
    listings = await conn.fetch(
        """
        select hl.id, hl.status, hl.created_at, hl.property_id,
               p.name, p.lat, p.lng
          from hunt_listings hl
          join properties p on p.id = hl.property_id
         where hl.hunt_id = $1
         order by hl.created_at, hl.id
        """,
        hunt_id,
    )
    active_count = sum(row["status"] == "active" for row in listings)
    archived = [row for row in listings if row["status"] == "archived"]
    blockers: list[str] = []
    warnings: list[str] = []
    captures: list[DemoCapture] = []

    missing_names = await conn.fetchval(
        """
        select count(*) from hunt_members
         where hunt_id = $1 and (display_name is null or btrim(display_name) = '')
        """,
        hunt_id,
    )
    if missing_names:
        blockers.append(f"{missing_names} Hunt member(s) need an explicit per-Hunt display name.")

    if len(archived) > MAX_REPLAY_CAPTURES:
        blockers.append(
            f"The Hunt has {len(archived)} archived Listings; Demo releases allow "
            f"at most {MAX_REPLAY_CAPTURES}."
        )

    for row in archived[:MAX_REPLAY_CAPTURES]:
        job_id = await conn.fetchval(
            """
            select id from jobs
             where hunt_listing_id = $1 and type = 'ingest' and state = 'done'
             order by finished_at desc nulls last, id desc
             limit 1
            """,
            row["id"],
        )
        if job_id is None:
            blockers.append(f"{row['name']} has no completed ingest Job to replay.")
            continue
        try:
            payload = await export_demo_capture(conn, job_id)
        except CaptureError as error:
            blockers.append(f"{row['name']} cannot be replayed: {error}")
            continue
        # Publication time is provenance, not a source input. Keeping it out of
        # the hash makes an unchanged Hunt fingerprint stable across preflights.
        payload.pop("exported_at", None)
        encoded = _canonical(payload)
        if len(encoded) > MAX_CAPTURE_BYTES:
            blockers.append(
                f"{row['name']}'s sanitized replay is {len(encoded):,} bytes; "
                f"the limit is {MAX_CAPTURE_BYTES:,}."
            )
            continue
        captures.append(
            DemoCapture(
                listing_id=row["id"],
                job_id=job_id,
                payload=payload,
                payload_bytes=len(encoded),
                fingerprint=hashlib.sha256(encoded).hexdigest(),
            )
        )

    places = [
        DemoPlace(
            property_id=row["property_id"],
            name=row["name"],
            lat=float(row["lat"]),
            lng=float(row["lng"]),
        )
        for row in listings
        if row["lat"] is not None and row["lng"] is not None
    ]
    # A Property is unique inside a Hunt, but de-duplicate defensively so one
    # future schema relaxation cannot multiply billable map calls.
    places = list({place.property_id: place for place in places}.values())
    places.sort(key=lambda place: str(place.property_id))
    missing_maps = len(listings) - len(places)
    if missing_maps:
        warnings.append(
            f"{missing_maps} Listing{'s' if missing_maps != 1 else ''} lack coordinates and "
            "will use the honest no-map state."
        )
    if len(places) > MAX_MAPPED_PROPERTIES:
        blockers.append(
            f"The Hunt has {len(places)} mapped Properties; Demo releases allow at most "
            f"{MAX_MAPPED_PROPERTIES}."
        )

    fingerprint = _digest(
        {
            "hunt_id": hunt_id,
            "listings": [
                {
                    "id": row["id"],
                    "status": row["status"],
                    "property_id": row["property_id"],
                    "name": row["name"],
                    "lat": row["lat"],
                    "lng": row["lng"],
                }
                for row in listings
            ],
            "captures": [
                {"listing_id": c.listing_id, "job_id": c.job_id, "hash": c.fingerprint}
                for c in captures
            ],
        }
    )
    return DemoSnapshot(
        hunt_id=hunt_id,
        fingerprint=fingerprint,
        active_count=active_count,
        archived_count=len(archived),
        captures=captures,
        places=places[:MAX_MAPPED_PROPERTIES],
        blockers=blockers,
        warnings=warnings,
    )


def _project(lat: float, lng: float) -> tuple[float, float]:
    siny = min(max(math.sin(math.radians(lat)), -0.9999), 0.9999)
    return (
        TILE * (0.5 + lng / 360),
        TILE * (0.5 - math.log((1 + siny) / (1 - siny)) / (4 * math.pi)),
    )


def _fit(places: list[DemoPlace]) -> tuple[float, float, int]:
    lats = [place.lat for place in places]
    lngs = [place.lng for place in places]
    center = ((min(lats) + max(lats)) / 2, (min(lngs) + max(lngs)) / 2)
    if len(places) == 1:
        return center[0], center[1], DRAWER_ZOOM
    southwest = _project(min(lats), min(lngs))
    northeast = _project(max(lats), max(lngs))
    span_x = abs(northeast[0] - southwest[0]) or 1e-9
    span_y = abs(southwest[1] - northeast[1]) or 1e-9
    width = max(HUNT_SIZE[0] - 2 * HUNT_PADDING_PX, 1)
    height = max(HUNT_SIZE[1] - 2 * HUNT_PADDING_PX, 1)
    zoom = min(math.floor(math.log2(width / span_x)), math.floor(math.log2(height / span_y)))
    return center[0], center[1], max(0, min(21, zoom))


def _map_url(
    center: tuple[float, float], zoom: int, size: tuple[int, int], dark: bool, key: str
) -> str:
    params: list[tuple[str, str]] = [
        ("center", f"{center[0]},{center[1]}"),
        ("zoom", str(zoom)),
        ("size", f"{size[0]}x{size[1]}"),
        ("scale", str(SCALE)),
        ("format", "png"),
        ("maptype", "roadmap"),
    ]
    params.extend(("style", style) for style in (DARK_STYLE if dark else LIGHT_STYLE))
    params.append(("key", key))
    return f"{STATIC_MAPS}?{urlencode(params)}"


async def _render_map(
    client: httpx.AsyncClient,
    center: tuple[float, float],
    zoom: int,
    size: tuple[int, int],
    dark: bool,
    key: str,
) -> bytes:
    # Never let httpx's exception text escape here: it includes the full request
    # URL, whose query string contains the server Maps key. Publication failures
    # are persisted and shown in Admin, so that would turn an upstream error
    # into a durable credential leak.
    try:
        response = await client.get(_map_url(center, zoom, size, dark, key))
    except httpx.HTTPError as error:
        raise RuntimeError(f"Google Static Maps request failed ({type(error).__name__})") from None
    if response.status_code != 200:
        raise RuntimeError(f"Google Static Maps returned HTTP {response.status_code}")
    if not response.content.startswith(b"\x89PNG"):
        raise RuntimeError("Google Static Maps returned a non-PNG response")
    try:
        image = Image.open(io.BytesIO(response.content)).convert("RGB")
        output = io.BytesIO()
        image.save(output, "WEBP", quality=82, method=6)
    except (OSError, UnidentifiedImageError) as error:
        raise RuntimeError("Google Static Maps returned an invalid image") from error
    return output.getvalue()


async def _publish_maps(
    publication_id: UUID, places: list[DemoPlace], store: SupabaseImageStore
) -> dict[str, Any]:
    if not places:
        return {"scale": SCALE, "tileSize": TILE, "properties": {}, "hunt": None}
    key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GOOGLE_MAPS_API_KEY is not configured for Demo publication")

    manifest: dict[str, Any] = {
        "scale": SCALE,
        "tileSize": TILE,
        "properties": {},
        "hunt": None,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        # A 100-Property release is 202 external renders. Sequential calls can
        # monopolize the single in-process worker for many minutes; a small
        # bound keeps it operational without turning publication into a burst
        # against Google or Storage.
        semaphore = asyncio.Semaphore(4)

        async def render_and_store(
            path: str,
            center: tuple[float, float],
            zoom: int,
            size: tuple[int, int],
            dark: bool,
        ) -> str:
            async with semaphore:
                content = await _render_map(client, center, zoom, size, dark, key)
                await store.put(path, content)
            return path

        async def collect(tasks: list[asyncio.Task[str]]) -> list[str]:
            try:
                return await asyncio.gather(*tasks)
            except BaseException:
                # `gather` does not cancel siblings when one request fails.
                # Leaving them alive would keep spending quota and uploading
                # inert objects after this publication has already failed.
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise

        property_tasks: list[tuple[DemoPlace, str, asyncio.Task[str]]] = []
        for place in places:
            for scheme, dark in (("light", False), ("dark", True)):
                path = f"releases/{publication_id}/properties/{place.property_id}-{scheme}.webp"
                property_tasks.append(
                    (
                        place,
                        scheme,
                        asyncio.create_task(
                            render_and_store(
                                path,
                                (place.lat, place.lng),
                                DRAWER_ZOOM,
                                DRAWER_SIZE,
                                dark,
                            )
                        ),
                    )
                )
        if property_tasks:
            paths = await collect([task for _, _, task in property_tasks])
            for (place, scheme, _), path in zip(property_tasks, paths, strict=True):
                entry = manifest["properties"].setdefault(
                    str(place.property_id),
                    {
                        "center": {"lat": place.lat, "lng": place.lng},
                        "zoom": DRAWER_ZOOM,
                        "size": {"width": DRAWER_SIZE[0], "height": DRAWER_SIZE[1]},
                        "images": {},
                    },
                )
                entry["images"][scheme] = path

        hunt_lat, hunt_lng, hunt_zoom = _fit(places)
        hunt_images: dict[str, str] = {}
        hunt_tasks: list[tuple[str, asyncio.Task[str]]] = []
        for scheme, dark in (("light", False), ("dark", True)):
            path = f"releases/{publication_id}/hunt-{scheme}.webp"
            hunt_tasks.append(
                (
                    scheme,
                    asyncio.create_task(
                        render_and_store(path, (hunt_lat, hunt_lng), hunt_zoom, HUNT_SIZE, dark)
                    ),
                )
            )
        hunt_paths = await collect([task for _, task in hunt_tasks])
        for (scheme, _), path in zip(hunt_tasks, hunt_paths, strict=True):
            hunt_images[scheme] = path
        manifest["hunt"] = {
            "center": {"lat": hunt_lat, "lng": hunt_lng},
            "zoom": hunt_zoom,
            "size": {"width": HUNT_SIZE[0], "height": HUNT_SIZE[1]},
            "images": hunt_images,
        }
    return manifest


async def _claim(conn: asyncpg.Connection, worker_id: str) -> asyncpg.Record | None:
    async with conn.transaction():
        # Publication work is durable too. A process can die between claiming
        # and promotion, so reclaim its lease just like the ordinary Job queue.
        # Heartbeats below distinguish a long map build from an orphan.
        await conn.execute(
            """
            update private.demo_publications
               set state = case when attempts >= 3 then 'failed' else 'queued' end,
                   error = case when attempts >= 3
                       then 'dead-lettered: publication worker lost its lease after 3 attempts'
                       else 'publication worker lease expired; retrying' end,
                   finished_at = case when attempts >= 3 then now() else null end,
                   locked_by = null, locked_at = null
             where state = 'building'
               and coalesce(locked_at, '-infinity'::timestamptz)
                   < now() - make_interval(secs => $1)
            """,
            PUBLICATION_ORPHAN_AFTER_SECONDS,
        )
        row = await conn.fetchrow(
            """
            select * from private.demo_publications
             where state = 'queued'
             order by created_at
             for update skip locked
             limit 1
            """
        )
        if row is None:
            return None
        return await conn.fetchrow(
            """
            update private.demo_publications
               set state = 'building', attempts = attempts + 1, locked_by = $2,
                   locked_at = now(), started_at = coalesce(started_at, now()), error = null
             where id = $1 returning *
            """,
            row["id"],
            worker_id,
        )


async def _heartbeat(
    pool: asyncpg.Pool,
    publication_id: UUID,
    worker_id: str,
    stop: asyncio.Event,
) -> None:
    """Keep a live map build from being mistaken for a crashed worker."""
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=PUBLICATION_HEARTBEAT_SECONDS)
            return
        except TimeoutError:
            result = await pool.execute(
                """
                update private.demo_publications set locked_at = now()
                 where id = $1 and state = 'building' and locked_by = $2
                """,
                publication_id,
                worker_id,
            )
            if result == "UPDATE 0":
                return


async def _supersede(
    pool: asyncpg.Pool,
    publication_id: UUID,
    worker_id: str,
    reason: str,
) -> None:
    await pool.execute(
        """
        update private.demo_publications
           set state = 'superseded', error = $3, finished_at = now(),
               locked_by = null, locked_at = null
         where id = $1 and state = 'building' and locked_by = $2
        """,
        publication_id,
        worker_id,
        reason[:2000],
    )


async def _fail(
    pool: asyncpg.Pool,
    publication: asyncpg.Record,
    worker_id: str,
    error: Exception,
) -> None:
    retry = publication["attempts"] < 3
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            update private.demo_publications
               set state = $2, error = $3, locked_by = null, locked_at = null,
                   finished_at = case when $2 = 'failed' then now() else null end
             where id = $1 and state = 'building' and locked_by = $4
            """,
            publication["id"],
            "queued" if retry else "failed",
            str(error)[:2000],
            worker_id,
        )
    log.warning(
        "demo_publication_failed",
        publication_id=str(publication["id"]),
        retry=retry and result != "UPDATE 0",
        lease_owned=result != "UPDATE 0",
        error=str(error),
    )


async def process_next_demo_publication(pool: asyncpg.Pool) -> bool:
    """Claim and process one queued publication; return whether work was found."""
    worker_id = f"{socket.gethostname()}:{os.getpid()}:demo"
    async with pool.acquire() as conn:
        publication = await _claim(conn, worker_id)
    if publication is None:
        return False

    heartbeat_stop = asyncio.Event()
    heartbeat_task = asyncio.create_task(
        _heartbeat(pool, publication["id"], worker_id, heartbeat_stop)
    )
    try:
        async with pool.acquire() as conn:
            snapshot = await build_demo_snapshot(conn, publication["hunt_id"])
        if snapshot.blockers:
            await _supersede(
                pool,
                publication["id"],
                worker_id,
                "; ".join(snapshot.blockers),
            )
            return True
        if snapshot.fingerprint != publication["source_fingerprint"]:
            await _supersede(
                pool,
                publication["id"],
                worker_id,
                "Hunt changed while publication was queued",
            )
            return True
        async with pool.acquire() as conn:
            security = list(await conn.fetchval("select private.demo_security_preflight()") or [])
        if security:
            await _supersede(
                pool,
                publication["id"],
                worker_id,
                "Demo security preflight failed: " + "; ".join(security),
            )
            return True

        storage_url = os.environ.get("SUPABASE_URL", "").strip()
        storage_key = os.environ.get("SUPABASE_SECRET_KEY", "").strip()
        if not storage_url or not storage_key:
            raise RuntimeError("SUPABASE_URL / SUPABASE_SECRET_KEY are not configured")
        store = SupabaseImageStore(storage_url, storage_key, bucket="demo-assets")
        manifest = await _publish_maps(publication["id"], snapshot.places, store)

        # Detect edits that raced the external map calls. No partial release is
        # ever promoted; versioned uploaded objects are inert without the DB id.
        async with pool.acquire() as conn:
            fresh = await build_demo_snapshot(conn, publication["hunt_id"])
        if fresh.blockers or fresh.fingerprint != snapshot.fingerprint:
            reason = (
                "; ".join(fresh.blockers) if fresh.blockers else "Hunt changed during publication"
            )
            await _supersede(pool, publication["id"], worker_id, reason)
            return True

        async with pool.acquire() as conn, conn.transaction():
            lease = await conn.fetchrow(
                """
                select state, locked_by from private.demo_publications
                 where id = $1 for update
                """,
                publication["id"],
            )
            if lease is None or lease["state"] != "building" or lease["locked_by"] != worker_id:
                raise RuntimeError("Demo publication worker lost its lease before promotion")
            config = await conn.fetchrow(
                """
                select demo_generation, demo_hunt_id, demo_release_id
                  from site_settings for update
                """
            )
            owner_ok = await conn.fetchval(
                """
                select exists (
                    select 1 from hunts h join site_admins sa on sa.user_id = h.owner_id
                     where h.id = $1 and h.owner_id = $2
                )
                """,
                publication["hunt_id"],
                publication["requested_by"],
            )
            if not owner_ok or config["demo_generation"] != publication["expected_generation"]:
                await conn.execute(
                    """
                    update private.demo_publications
                       set state = 'superseded', error = 'Configuration or ownership changed',
                           finished_at = now(), locked_by = null, locked_at = null
                     where id = $1 and state = 'building' and locked_by = $2
                    """,
                    publication["id"],
                    worker_id,
                )
                return True

            await conn.executemany(
                """
                insert into private.demo_replay_captures
                    (publication_id, ordinal, hunt_listing_id, job_id, payload,
                     payload_bytes, fingerprint)
                values ($1, $2, $3, $4, $5::jsonb, $6, $7)
                """,
                [
                    (
                        publication["id"],
                        ordinal,
                        capture.listing_id,
                        capture.job_id,
                        json.dumps(capture.payload),
                        capture.payload_bytes,
                        capture.fingerprint,
                    )
                    for ordinal, capture in enumerate(snapshot.captures)
                ],
            )
            await conn.execute(
                """
                update private.demo_publications
                   set state = 'ready', map_manifest = $2::jsonb, replay_count = $3,
                       mapped_count = $4, warnings = $5::jsonb, error = null,
                       finished_at = now(), published_at = now(), locked_by = null, locked_at = null
                 where id = $1
                """,
                publication["id"],
                json.dumps(manifest),
                len(snapshot.captures),
                len(snapshot.places),
                json.dumps(snapshot.warnings),
            )
            new_generation = config["demo_generation"] + 1
            await conn.execute(
                """
                update site_settings
                   set demo_hunt_id = $1, demo_release_id = $2,
                       demo_enabled = case when $3 then true else demo_enabled end,
                       demo_generation = $4, updated_by = $5, updated_at = now()
                """,
                publication["hunt_id"],
                publication["id"],
                publication["enable_on_success"],
                new_generation,
                publication["requested_by"],
            )
            problems = await conn.fetchval("select private.demo_preflight()")
            if problems:
                raise RuntimeError("Demo preflight failed at promotion: " + "; ".join(problems))
            await conn.execute(
                """
                insert into admin_audit_log
                    (admin_user_id, action, target_type, target_id, target_label,
                     hunt_id, before, after, via_ghost_view)
                values ($1, 'demo.publish', 'demo_publication', $2, 'Demo release',
                        $3, $4::jsonb, $5::jsonb, false)
                """,
                publication["requested_by"],
                publication["id"],
                publication["hunt_id"],
                json.dumps(
                    {
                        "hunt_id": str(config["demo_hunt_id"]) if config["demo_hunt_id"] else None,
                        "release_id": str(config["demo_release_id"])
                        if config["demo_release_id"]
                        else None,
                    }
                ),
                json.dumps(
                    {
                        "hunt_id": str(publication["hunt_id"]),
                        "release_id": str(publication["id"]),
                        "enabled": bool(publication["enable_on_success"]),
                    }
                ),
            )
        log.info("demo_publication_ready", publication_id=str(publication["id"]))
    except Exception as error:
        await _fail(pool, publication, worker_id, error)
    finally:
        heartbeat_stop.set()
        try:
            await heartbeat_task
        except Exception:
            log.warning(
                "demo_publication_heartbeat_failed",
                publication_id=str(publication["id"]),
                exc_info=True,
            )
    return True


__all__ = [
    "MAX_CAPTURE_BYTES",
    "MAX_MAPPED_PROPERTIES",
    "MAX_REPLAY_CAPTURES",
    "DemoSnapshot",
    "build_demo_snapshot",
    "process_next_demo_publication",
]
