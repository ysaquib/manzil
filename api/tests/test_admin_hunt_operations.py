"""The Ghost View write choke point: elevated, conditional, and audited."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import UUID

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from manzil_api.admin.dependencies import AdminAudit
from manzil_api.main import create_app

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def ghost_client(db_pool, seeded_users) -> AsyncIterator[AsyncClient]:  # type: ignore[no-untyped-def]
    identity = seeded_users["outsider"]
    await db_pool.execute(
        "insert into site_admins(user_id) values($1) on conflict do nothing", identity.user_id
    )
    app = create_app()
    app.state.db_pool = db_pool
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {identity.token}"},
        ) as client:
            yield client
    finally:
        await db_pool.execute("delete from site_admins where user_id=$1", identity.user_id)


async def test_ghost_archives_a_listing_and_records_the_actor(
    ghost_client: AsyncClient, db_pool, collab_hunt, seeded_users
) -> None:
    listing_id = collab_hunt["owner_listing_id"]
    response = await ghost_client.patch(
        f"/v1/admin/ghost/listings/{listing_id}/status", json={"status": "archived"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "archived"

    audit = await db_pool.fetchrow(
        "select admin_user_id, hunt_id, via_ghost_view, after from admin_audit_log "
        "where action='listing.status.update' and target_id=$1 order by occurred_at desc limit 1",
        UUID(listing_id),
    )
    assert str(audit["admin_user_id"]) == seeded_users["outsider"].user_id
    assert str(audit["hunt_id"]) == collab_hunt["hunt_id"]
    assert audit["via_ghost_view"] is True
    after = json.loads(audit["after"]) if isinstance(audit["after"], str) else audit["after"]
    assert after["status"] == "archived"


async def test_ghost_permanently_deletes_an_archived_listing_atomically(
    ghost_client: AsyncClient, db_pool, collab_hunt, seeded_users
) -> None:
    listing_id = UUID(collab_hunt["owner_listing_id"])
    await db_pool.execute("update hunt_listings set status='archived' where id=$1", listing_id)

    impact = await ghost_client.get(f"/v1/admin/ghost/listings/{listing_id}/deletion-impact")
    assert impact.status_code == 200, impact.text
    assert impact.json()["property_name"] == "Owner Property"

    response = await ghost_client.request(
        "DELETE",
        f"/v1/admin/ghost/listings/{listing_id}",
        json={"confirmation_name": "Owner Property"},
    )
    assert response.status_code == 200, response.text
    assert (
        await db_pool.fetchval("select exists(select 1 from hunt_listings where id=$1)", listing_id)
        is False
    )
    audit = await db_pool.fetchrow(
        "select admin_user_id, via_ghost_view, before, after from admin_audit_log "
        "where action='listing.permanent_delete' and target_id=$1 "
        "order by occurred_at desc limit 1",
        listing_id,
    )
    assert str(audit["admin_user_id"]) == seeded_users["outsider"].user_id
    assert audit["via_ghost_view"] is True


async def test_ghost_delete_rolls_back_when_audit_fails(
    ghost_client: AsyncClient, db_pool, collab_hunt, monkeypatch
) -> None:
    listing_id = UUID(collab_hunt["owner_listing_id"])
    await db_pool.execute("update hunt_listings set status='archived' where id=$1", listing_id)

    async def fail_audit(*args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(AdminAudit, "record", fail_audit)
    response = await ghost_client.request(
        "DELETE",
        f"/v1/admin/ghost/listings/{listing_id}",
        json={"confirmation_name": "Owner Property"},
    )
    assert response.status_code == 500
    assert (
        await db_pool.fetchval("select exists(select 1 from hunt_listings where id=$1)", listing_id)
        is True
    )


async def test_admin_members_cannot_elevate_their_hunt_role(
    db_pool, collab_hunt, seeded_users
) -> None:
    await db_pool.execute(
        "insert into site_admins(user_id) values($1) on conflict do nothing",
        seeded_users["member"].user_id,
    )
    try:
        identity = seeded_users["member"]
        app = create_app()
        app.state.db_pool = db_pool
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {identity.token}"},
        ) as client:
            response = await client.patch(
                f"/v1/admin/ghost/listings/{collab_hunt['owner_listing_id']}/status",
                json={"status": "archived"},
            )
        assert response.status_code == 403
        assert response.json()["code"] == "ghost_view_unavailable"

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {identity.token}"},
        ) as client:
            response = await client.request(
                "DELETE",
                f"/v1/admin/ghost/listings/{collab_hunt['owner_listing_id']}",
                json={"confirmation_name": "Owner Property"},
            )
        assert response.status_code == 403
        assert response.json()["code"] == "ghost_view_unavailable"
        assert await db_pool.fetchval(
            "select exists(select 1 from hunt_listings where id=$1)",
            collab_hunt["owner_listing_id"],
        )
    finally:
        await db_pool.execute(
            "delete from site_admins where user_id=$1", seeded_users["member"].user_id
        )


async def test_ghost_submits_a_listing_with_admin_attribution(
    ghost_client: AsyncClient, db_pool, collab_hunt, seeded_users
) -> None:
    response = await ghost_client.post(
        f"/v1/admin/ghost/hunts/{collab_hunt['hunt_id']}/listings",
        json={"url": "https://example.test/admin-submission"},
    )
    assert response.status_code == 201, response.text
    listing_id = UUID(response.json()["id"])

    row = await db_pool.fetchrow(
        "select added_by, property_id from hunt_listings where id=$1", listing_id
    )
    assert str(row["added_by"]) == seeded_users["outsider"].user_id
    assert (
        await db_pool.fetchval(
            "select count(*) from jobs where hunt_listing_id=$1 and type='ingest'", listing_id
        )
        == 1
    )
    assert (
        await db_pool.fetchval(
            "select via_ghost_view from admin_audit_log where action='listing.create' "
            "and target_id=$1 order by occurred_at desc limit 1",
            listing_id,
        )
        is True
    )

    # The Hunt fixture removes the Listing; its Property is intentionally global
    # and therefore needs explicit cleanup here.
    await db_pool.execute("delete from hunt_listings where id=$1", listing_id)
    await db_pool.execute("delete from properties where id=$1", row["property_id"])


async def test_ghost_saves_the_rubric_through_the_audited_route(
    ghost_client: AsyncClient, db_pool, collab_hunt
) -> None:
    response = await ghost_client.put(
        f"/v1/admin/ghost/hunts/{collab_hunt['hunt_id']}/rubric",
        json={"criteria": []},
    )
    assert response.status_code == 200, response.text
    assert response.json() == []
    assert (
        await db_pool.fetchval(
            "select via_ghost_view from admin_audit_log where action='hunt.rubric.update' "
            "and hunt_id=$1 order by occurred_at desc limit 1",
            UUID(collab_hunt["hunt_id"]),
        )
        is True
    )


async def test_ghost_queues_a_listing_refresh(
    ghost_client: AsyncClient, db_pool, collab_hunt
) -> None:
    listing_id = UUID(collab_hunt["owner_listing_id"])
    source_id = await db_pool.fetchval(
        "select ps.id from property_sources ps join hunt_listings hl "
        "on hl.property_id=ps.property_id where hl.id=$1 limit 1",
        listing_id,
    )
    await db_pool.execute(
        "update property_sources set last_success_at=now() where id=$1", source_id
    )
    await db_pool.execute(
        "update hunt_listings set submitted_source_id=$2 where id=$1", listing_id, source_id
    )

    response = await ghost_client.post(f"/v1/admin/ghost/listings/{listing_id}/refresh", json={})
    assert response.status_code == 202, response.text
    assert response.json()["type"] == "refresh"
    assert (
        await db_pool.fetchval(
            "select via_ghost_view from admin_audit_log where action='listing.refresh' "
            "and target_id=$1 order by occurred_at desc limit 1",
            listing_id,
        )
        is True
    )
