"""P3-SC5 diagram lifecycle: retirement, purge, and the same-Property invariant.

These exercise the rules that decide whether a diagram survives an operation.
Every one of them is a data-loss guard: the failure mode is a plan quietly
losing its layout, which the UI cannot distinguish from "never had one".
"""

from __future__ import annotations

from uuid import UUID, uuid4

import asyncpg
import pytest
from manzil_worker.ops.purge_images import purge_unreferenced_images


async def _property(pool: asyncpg.Pool, name: str = "Diagrams") -> UUID:
    property_id = uuid4()
    await pool.execute(
        "insert into properties (id, name, canonical_address) values ($1, $2, '1 Test')",
        property_id,
        name,
    )
    return property_id


async def _source(pool: asyncpg.Pool, property_id: UUID, slug: str) -> UUID:
    source_id = uuid4()
    await pool.execute(
        "insert into property_sources (id, property_id, url, site_domain) "
        "values ($1, $2, $3, 'example.com')",
        source_id,
        property_id,
        f"https://example.com/{slug}",
    )
    return source_id


async def _plan(pool: asyncpg.Pool, property_id: UUID, source_id: UUID, name: str) -> UUID:
    return await pool.fetchval(
        "insert into floor_plans (property_id, source_id, plan_name, beds, baths) "
        "values ($1, $2, $3, 2, 2) returning id",
        property_id,
        source_id,
        name,
    )


async def _image(
    pool: asyncpg.Pool,
    property_id: UUID,
    source_id: UUID,
    digest: str,
    *,
    is_current: bool = True,
) -> UUID:
    return await pool.fetchval(
        """
        insert into property_images
            (property_id, source_id, source_url, storage_path, content_hash,
             kind, is_current)
        values ($1, $2, $3, $4, $5, 'floor_plan_diagram', $6)
        returning id
        """,
        property_id,
        source_id,
        f"https://example.com/{digest}.png",
        f"properties/{property_id}/{digest}.webp",
        digest,
        is_current,
    )


async def _link(
    pool: asyncpg.Pool, plan_id: UUID, image_id: UUID, source_id: UUID, action: str = "link"
) -> None:
    await pool.execute(
        """
        insert into floor_plan_images
            (floor_plan_id, property_image_id, source_id, action,
             association_method, confidence, evidence_context)
        values ($1, $2, $3, $4, 'containing_card', 'high', '{}'::jsonb)
        """,
        plan_id,
        image_id,
        source_id,
        action,
    )


async def test_unlink_drops_the_pair_from_the_current_view_but_keeps_history(
    pg_pool: asyncpg.Pool,
) -> None:
    property_id = await _property(pg_pool)
    try:
        source_id = await _source(pg_pool, property_id, "a")
        plan_id = await _plan(pg_pool, property_id, source_id, "Winslow")
        image_id = await _image(pg_pool, property_id, source_id, "aa" * 16)

        await _link(pg_pool, plan_id, image_id, source_id)
        assert await pg_pool.fetchval(
            "select count(*) from current_floor_plan_images where floor_plan_id = $1", plan_id
        )

        await _link(pg_pool, plan_id, image_id, source_id, action="unlink")
        assert (
            await pg_pool.fetchval(
                "select count(*) from current_floor_plan_images where floor_plan_id = $1", plan_id
            )
            == 0
        )
        # Append-only: both observations survive for provenance.
        assert (
            await pg_pool.fetchval(
                "select count(*) from floor_plan_images where floor_plan_id = $1", plan_id
            )
            == 2
        )

        # Reappearing content re-links the same content-hash asset.
        await _link(pg_pool, plan_id, image_id, source_id)
        assert await pg_pool.fetchval(
            "select count(*) from current_floor_plan_images where floor_plan_id = $1", plan_id
        )
    finally:
        await pg_pool.execute("delete from properties where id = $1", property_id)


async def test_association_across_two_properties_is_refused(pg_pool: asyncpg.Pool) -> None:
    """The same-Property invariant is enforced by the database, not by hope."""
    left = await _property(pg_pool, "Left")
    right = await _property(pg_pool, "Right")
    try:
        left_source = await _source(pg_pool, left, "left")
        right_source = await _source(pg_pool, right, "right")
        plan_id = await _plan(pg_pool, left, left_source, "Winslow")
        foreign_image = await _image(pg_pool, right, right_source, "bb" * 16)

        with pytest.raises(asyncpg.PostgresError, match="within one Property"):
            await _link(pg_pool, plan_id, foreign_image, left_source)
    finally:
        await pg_pool.execute("delete from properties where id = any($1::uuid[])", [left, right])


async def test_purge_removes_only_unreferenced_non_current_images(
    pg_pool: asyncpg.Pool,
) -> None:
    property_id = await _property(pg_pool)
    try:
        source_id = await _source(pg_pool, property_id, "a")
        plan_id = await _plan(pg_pool, property_id, source_id, "Winslow")

        displayed = await _image(pg_pool, property_id, source_id, "c1" * 16)
        associated = await _image(pg_pool, property_id, source_id, "c2" * 16, is_current=False)
        orphan = await _image(pg_pool, property_id, source_id, "c3" * 16, is_current=False)
        await _link(pg_pool, plan_id, associated, source_id)

        class Store:
            def __init__(self) -> None:
                self.deleted: list[str] = []

            async def put(self, path: str, content: bytes) -> None: ...
            async def get(self, path: str) -> bytes: ...
            async def delete(self, path: str) -> None:
                self.deleted.append(path)

        store = Store()
        preview = await purge_unreferenced_images(
            pg_pool, store, property_id=property_id, dry_run=True
        )
        assert preview.considered == 1 and not store.deleted

        result = await purge_unreferenced_images(pg_pool, store, property_id=property_id)
        assert result.deleted_rows == 1
        assert len(store.deleted) == 1

        survivors = {
            row["id"]
            for row in await pg_pool.fetch(
                "select id from property_images where property_id = $1", property_id
            )
        }
        assert displayed in survivors  # still displayed
        assert associated in survivors  # still evidences a plan
        assert orphan not in survivors
    finally:
        await pg_pool.execute("delete from properties where id = $1", property_id)


async def test_purge_keeps_bytes_another_property_still_references(
    pg_pool: asyncpg.Pool,
) -> None:
    """Storage is content-addressed and shared; purging one Property must not
    delete an object another Property still points at."""
    left = await _property(pg_pool, "Left")
    right = await _property(pg_pool, "Right")
    try:
        left_source = await _source(pg_pool, left, "left")
        right_source = await _source(pg_pool, right, "right")
        shared_path = "properties/shared/dd.webp"
        sides = ((left, left_source, False), (right, right_source, True))
        for property_id, source_id, current in sides:
            await pg_pool.execute(
                """
                insert into property_images
                    (property_id, source_id, source_url, storage_path, content_hash,
                     kind, is_current)
                values ($1, $2, 'https://example.com/d.png', $3, 'dd', 'floor_plan_diagram', $4)
                """,
                property_id,
                source_id,
                shared_path,
                current,
            )

        class Store:
            def __init__(self) -> None:
                self.deleted: list[str] = []

            async def put(self, path: str, content: bytes) -> None: ...
            async def get(self, path: str) -> bytes: ...
            async def delete(self, path: str) -> None:
                self.deleted.append(path)

        store = Store()
        result = await purge_unreferenced_images(pg_pool, store, property_id=left)

        assert result.deleted_rows == 1  # the row goes
        assert store.deleted == []  # the shared object stays
        assert result.retained_shared == 1
    finally:
        await pg_pool.execute("delete from properties where id = any($1::uuid[])", [left, right])
