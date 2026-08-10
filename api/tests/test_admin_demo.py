"""Admin-managed Demo Hunt publication contracts (DESIGN §20 v3.72)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from manzil_api.main import create_app
from manzil_worker.ops.demo_publication import process_next_demo_publication

pytestmark = pytest.mark.asyncio


async def _queue_empty_release(
    client: AsyncClient,
    hunt_id: UUID,
    *,
    enable_on_success: bool = False,
) -> UUID:
    review = await client.post("/v1/admin/demo/preflight", json={"hunt_id": str(hunt_id)})
    assert review.status_code == 200, review.text
    queued = await client.post(
        "/v1/admin/demo/publications",
        json={
            "confirmation_id": review.json()["confirmation_id"],
            "confirmation_text": "Public showcase",
            "enable_on_success": enable_on_success,
        },
    )
    assert queued.status_code == 202, queued.text
    return UUID(queued.json()["publication_id"])


@pytest_asyncio.fixture
async def demo_admin(db_pool, seeded_users) -> AsyncIterator[tuple[AsyncClient, UUID]]:
    identity = seeded_users["outsider"]
    app = create_app()
    app.state.db_pool = db_pool
    markers = [
        dict(row)
        for row in await db_pool.fetch("select user_id, created_by, note from demo_accounts")
    ]
    await db_pool.execute(
        "insert into site_admins (user_id) values ($1) on conflict do nothing",
        identity.user_id,
    )
    hunt_id = await db_pool.fetchval(
        "insert into hunts (name, owner_id) values ('Public showcase', $1) returning id",
        identity.user_id,
    )
    await db_pool.execute(
        "update hunt_members set display_name = 'Showcase owner' where hunt_id = $1",
        hunt_id,
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {identity.token}"},
        ) as client:
            yield client, hunt_id
    finally:
        await db_pool.execute(
            """
            update site_settings
               set demo_enabled = false, demo_hunt_id = null, demo_release_id = null
             where demo_hunt_id = $1
            """,
            hunt_id,
        )
        await db_pool.execute("delete from private.demo_publications where hunt_id = $1", hunt_id)
        await db_pool.execute(
            "delete from private.demo_publish_confirmations where hunt_id = $1", hunt_id
        )
        await db_pool.execute("delete from hunts where id = $1", hunt_id)
        await db_pool.execute("delete from demo_accounts")
        for marker in markers:
            await db_pool.execute(
                "insert into demo_accounts (user_id, created_by, note) values ($1, $2, $3)",
                marker["user_id"],
                marker["created_by"],
                marker["note"],
            )
        await db_pool.execute("delete from site_admins where user_id = $1", identity.user_id)


async def test_candidates_are_owned_and_cross_owner_preflight_is_refused(
    demo_admin, collab_hunt
) -> None:
    client, hunt_id = demo_admin
    candidates = await client.get("/v1/admin/demo/hunts")
    assert candidates.status_code == 200
    assert {row["hunt_id"] for row in candidates.json()} == {str(hunt_id)}

    refused = await client.post(
        "/v1/admin/demo/preflight", json={"hunt_id": collab_hunt["hunt_id"]}
    )
    assert refused.status_code == 404
    assert refused.json()["code"] == "demo_hunt_not_found"


async def test_review_confirmation_queues_and_promotes_an_atomic_release(
    demo_admin, db_pool
) -> None:
    client, hunt_id = demo_admin
    review = await client.post("/v1/admin/demo/preflight", json={"hunt_id": str(hunt_id)})
    assert review.status_code == 200, review.text
    body = review.json()
    assert body["blockers"] == []
    assert body["active_listings"] == 0
    assert body["archived_listings"] == 0

    wrong_name = await client.post(
        "/v1/admin/demo/publications",
        json={
            "confirmation_id": body["confirmation_id"],
            "confirmation_text": "not the Hunt name",
            "enable_on_success": False,
        },
    )
    assert wrong_name.status_code == 409

    queued = await client.post(
        "/v1/admin/demo/publications",
        json={
            "confirmation_id": body["confirmation_id"],
            "confirmation_text": "Public showcase",
            "enable_on_success": False,
        },
    )
    assert queued.status_code == 202, queued.text
    publication_id = UUID(queued.json()["publication_id"])

    assert await process_next_demo_publication(db_pool)
    publication = await db_pool.fetchrow(
        "select state, replay_count, mapped_count from private.demo_publications where id = $1",
        publication_id,
    )
    assert dict(publication) == {"state": "ready", "replay_count": 0, "mapped_count": 0}
    config = await db_pool.fetchrow(
        "select demo_enabled, demo_hunt_id, demo_release_id from site_settings"
    )
    assert config["demo_enabled"] is False
    assert config["demo_hunt_id"] == hunt_id
    assert config["demo_release_id"] == publication_id

    enabled = await client.patch("/v1/admin/demo", json={"enabled": True})
    assert enabled.status_code == 200, enabled.text
    session = await client.post("/v1/demo/session")
    assert session.status_code == 200, session.text
    demo_headers = {"Authorization": f"Bearer {session.json()['access_token']}"}

    release = await client.get("/v1/demo/release", headers=demo_headers)
    assert release.status_code == 200, release.text
    assert release.json()["release_id"] == str(publication_id)
    assert release.json()["capture_ordinals"] == []
    assert release.headers["cache-control"] == "private, no-store"

    # Neither an ordinal nor an object path is authority. Both must be members
    # of the current release before the API will return anything.
    missing_capture = await client.get("/v1/demo/release/captures/0", headers=demo_headers)
    missing_map = await client.get(
        "/v1/demo/release/maps/releases/guessed/map.webp", headers=demo_headers
    )
    assert missing_capture.status_code == 404
    assert missing_map.status_code == 404

    disabled = await client.patch("/v1/admin/demo", json={"enabled": False})
    assert disabled.status_code == 200
    revoked = await client.get("/v1/demo/release", headers=demo_headers)
    assert revoked.status_code == 404


async def test_publication_rechecks_preflight_blockers_server_side(demo_admin, db_pool) -> None:
    client, hunt_id = demo_admin
    review = await client.post("/v1/admin/demo/preflight", json={"hunt_id": str(hunt_id)})
    assert review.status_code == 200, review.text
    await db_pool.execute(
        "update hunt_members set display_name = null where hunt_id = $1", hunt_id
    )

    bypass = await client.post(
        "/v1/admin/demo/publications",
        json={
            "confirmation_id": review.json()["confirmation_id"],
            "confirmation_text": "Public showcase",
            "enable_on_success": False,
        },
    )

    assert bypass.status_code == 409
    assert "display name" in bypass.json()["detail"]
    assert (
        await db_pool.fetchval(
            "select count(*) from private.demo_publications where hunt_id = $1", hunt_id
        )
        == 0
    )


async def test_retained_selection_cannot_be_reenabled_by_publication_flag(
    demo_admin, db_pool
) -> None:
    client, hunt_id = demo_admin
    first = await _queue_empty_release(client, hunt_id)
    assert await process_next_demo_publication(db_pool)
    assert (
        await db_pool.fetchval("select state from private.demo_publications where id = $1", first)
        == "ready"
    )

    review = await client.post("/v1/admin/demo/preflight", json={"hunt_id": str(hunt_id)})
    assert review.status_code == 200, review.text
    refused = await client.post(
        "/v1/admin/demo/publications",
        json={
            "confirmation_id": review.json()["confirmation_id"],
            "confirmation_text": "Public showcase",
            "enable_on_success": True,
        },
    )

    assert refused.status_code == 409
    assert "enabled explicitly" in refused.json()["detail"]


async def test_release_capture_survives_after_its_live_provenance_is_gone(
    demo_admin, db_pool
) -> None:
    client, hunt_id = demo_admin
    publication_id = await _queue_empty_release(client, hunt_id)
    assert await process_next_demo_publication(db_pool)
    await db_pool.execute(
        """
        insert into private.demo_replay_captures
            (publication_id, ordinal, hunt_listing_id, job_id, payload,
             payload_bytes, fingerprint)
        values ($1, 0, $2, $3, '{"version": 1}'::jsonb, 14, 'capture-hash')
        """,
        publication_id,
        uuid4(),
        uuid4(),
    )
    await db_pool.execute(
        "update private.demo_publications set replay_count = 1 where id = $1",
        publication_id,
    )
    enabled = await client.patch("/v1/admin/demo", json={"enabled": True})
    assert enabled.status_code == 200, enabled.text
    session = await client.post("/v1/demo/session")
    assert session.status_code == 200, session.text
    headers = {"Authorization": f"Bearer {session.json()['access_token']}"}

    release = await client.get("/v1/demo/release", headers=headers)
    capture = await client.get("/v1/demo/release/captures/0", headers=headers)

    assert release.status_code == 200
    assert release.json()["capture_ordinals"] == [0]
    assert capture.status_code == 200
    assert capture.json() == {"version": 1}


async def test_transfer_to_another_site_admin_revokes_the_old_owner_release(
    demo_admin, db_pool, seeded_users
) -> None:
    client, hunt_id = demo_admin
    publication_id = await _queue_empty_release(client, hunt_id)
    assert await process_next_demo_publication(db_pool)
    assert await client.patch("/v1/admin/demo", json={"enabled": True})
    session = await client.post("/v1/demo/session")
    assert session.status_code == 200, session.text
    headers = {"Authorization": f"Bearer {session.json()['access_token']}"}
    new_owner = seeded_users["curator"].user_id
    await db_pool.execute(
        "insert into site_admins (user_id) values ($1) on conflict do nothing", new_owner
    )
    try:
        await db_pool.execute("update hunts set owner_id = $1 where id = $2", new_owner, hunt_id)

        release = await client.get("/v1/demo/release", headers=headers)
        available = await db_pool.fetchval("select demo_available()")

        assert release.status_code == 404
        assert available is False
        assert (
            await db_pool.fetchval(
                "select requested_by from private.demo_publications where id = $1",
                publication_id,
            )
            != new_owner
        )
    finally:
        await db_pool.execute(
            "update hunts set owner_id = $1 where id = $2",
            seeded_users["outsider"].user_id,
            hunt_id,
        )
        await db_pool.execute("delete from site_admins where user_id = $1", new_owner)


async def test_orphaned_publication_is_reclaimed_and_completed(demo_admin, db_pool) -> None:
    client, hunt_id = demo_admin
    review = await client.post("/v1/admin/demo/preflight", json={"hunt_id": str(hunt_id)})
    assert review.status_code == 200, review.text
    actor = await db_pool.fetchval("select owner_id from hunts where id = $1", hunt_id)
    generation = await db_pool.fetchval("select demo_generation from site_settings")
    publication_id = await db_pool.fetchval(
        """
        insert into private.demo_publications
            (hunt_id, requested_by, state, expected_generation, source_fingerprint,
             attempts, locked_by, locked_at, started_at)
        values ($1, $2, 'building', $3, $4, 1, 'dead-worker', now() - interval '1 hour',
                now() - interval '1 hour')
        returning id
        """,
        hunt_id,
        actor,
        generation,
        review.json()["source_fingerprint"],
    )

    assert await process_next_demo_publication(db_pool)
    row = await db_pool.fetchrow(
        "select state, attempts, locked_by from private.demo_publications where id = $1",
        publication_id,
    )
    assert dict(row) == {"state": "ready", "attempts": 2, "locked_by": None}


async def test_release_schema_keeps_history_without_blocking_source_deletion(db_pool) -> None:
    constraints = {
        row["column_name"]: row["delete_rule"]
        for row in await db_pool.fetch(
            """
            select kcu.column_name, rc.delete_rule
              from information_schema.referential_constraints rc
              join information_schema.key_column_usage kcu
                on kcu.constraint_schema = rc.constraint_schema
               and kcu.constraint_name = rc.constraint_name
             where kcu.table_schema = 'private'
               and kcu.table_name in ('demo_publications', 'demo_replay_captures')
            """
        )
    }

    assert constraints["hunt_id"] == "CASCADE"
    assert "requested_by" not in constraints
    assert "hunt_listing_id" not in constraints
    assert "job_id" not in constraints
