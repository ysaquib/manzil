"""Explicit image purge (P3-SC5 §9.3 third-party diagram posture).

DESIGN's retention rule is deliberately conservative: *inactive evidence is
preserved while its Property remains stored*, and removal happens only through
an explicit purge path. So this is not a scheduled sweep and not a TTL — it is
an admin action, and it refuses to guess.

What it removes: Storage objects for images that are non-current, carry no
current Floor Plan association, and are not cited by any Extraction. What it
never removes: anything still displayed, anything still evidencing a score, and
— unless `--property` scopes it — anything at all outside one Property.

Byte deletion is content-addressed and shared: two `property_images` rows on
different Properties can name the same object. The candidate query is therefore
resolved to storage paths *globally* before anything is deleted, so purging one
Property can never orphan another's still-referenced bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import asyncpg
import structlog

from manzil_worker.enrich.images import ImageObjectStore

log = structlog.get_logger()


@dataclass(frozen=True)
class PurgeResult:
    considered: int
    deleted_objects: int
    deleted_rows: int
    retained_shared: int


async def purge_unreferenced_images(
    conn: asyncpg.Connection,
    store: ImageObjectStore,
    *,
    property_id: UUID | None = None,
    dry_run: bool = False,
) -> PurgeResult:
    """Delete Storage objects and rows for unreferenced, non-current images."""
    candidates = await conn.fetch(
        """
        select pi.id, pi.storage_path
        from property_images pi
        where not pi.is_current
          and ($1::uuid is null or pi.property_id = $1)
          and not exists (
              select 1 from current_floor_plan_images c
              where c.property_image_id = pi.id
          )
          and not exists (
              select 1 from extraction_images xi
              where xi.property_image_id = pi.id
          )
        """,
        property_id,
    )
    if not candidates:
        return PurgeResult(0, 0, 0, 0)

    paths = {row["storage_path"] for row in candidates}
    # A path is only safe to delete when *no* surviving row anywhere names it.
    still_referenced = {
        row["storage_path"]
        for row in await conn.fetch(
            """
            select distinct storage_path from property_images
            where storage_path = any($1::text[])
              and id <> all($2::uuid[])
            """,
            list(paths),
            [row["id"] for row in candidates],
        )
    }
    removable = sorted(paths - still_referenced)

    if dry_run:
        return PurgeResult(
            considered=len(candidates),
            deleted_objects=len(removable),
            deleted_rows=0,
            retained_shared=len(still_referenced),
        )

    deleted_objects = 0
    for path in removable:
        try:
            await store.delete(path)
            deleted_objects += 1
        except Exception as error:  # a missing object is already the goal state
            log.warning("image_purge_object_failed", path=path, error=str(error))
    status = await conn.execute(
        "delete from property_images where id = any($1::uuid[])",
        [row["id"] for row in candidates],
    )
    deleted_rows = int(status.split()[-1]) if status else 0
    log.info(
        "image_purge_done",
        property_id=str(property_id) if property_id else None,
        considered=len(candidates),
        deleted_objects=deleted_objects,
        deleted_rows=deleted_rows,
    )
    return PurgeResult(
        considered=len(candidates),
        deleted_objects=deleted_objects,
        deleted_rows=deleted_rows,
        retained_shared=len(still_referenced),
    )
