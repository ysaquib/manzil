"""Archive/lock are enforced at both the API seam and the database boundary."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from manzil_api.main import create_app
from postgrest.exceptions import APIError

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def lifecycle_hunt(db_pool, seeded_users) -> AsyncIterator[dict[str, str]]:  # type: ignore[no-untyped-def]
    owner = seeded_users["owner"]
    hunt_id = await db_pool.fetchval(
        "insert into hunts(name, owner_id) values('Lifecycle Hunt', $1) returning id",
        owner.user_id,
    )
    job_id = await db_pool.fetchval(
        "insert into jobs(hunt_id, type, state, payload) "
        # WAITING_USER is unfinished but cannot be claimed by a concurrently
        # running local worker between this fixture insert and the archive.
        "values($1, 'rescore', 'waiting_user', '{}'::jsonb) returning id",
        hunt_id,
    )
    try:
        yield {"hunt_id": str(hunt_id), "job_id": str(job_id)}
    finally:
        await db_pool.execute("delete from hunts where id=$1", hunt_id)


async def test_archive_remains_visible_but_refuses_every_write(
    as_owner: AsyncClient, db_pool, lifecycle_hunt, seeded_users
) -> None:
    hunt_id = lifecycle_hunt["hunt_id"]
    archived = await as_owner.patch(f"/v1/hunts/{hunt_id}", json={"archived": True})
    assert archived.status_code == 200, archived.text
    assert archived.json()["archived_at"] is not None

    hunts = await as_owner.get("/v1/hunts")
    assert hunt_id in {row["id"] for row in hunts.json()}
    assert (
        await db_pool.fetchval(
            "select state::text from jobs where id=$1", UUID(lifecycle_hunt["job_id"])
        )
        == "cancelled"
    )

    renamed = await as_owner.patch(f"/v1/hunts/{hunt_id}", json={"name": "Nope"})
    assert renamed.status_code == 409
    assert renamed.json()["code"] == "hunt_archived_read_only"

    with pytest.raises(APIError, match="hunt_archived_read_only"):
        (
            seeded_users["owner"]
            .supabase.table("hunt_members")
            .update({"color": "#123456"})
            .eq("hunt_id", hunt_id)
            .eq("user_id", seeded_users["owner"].user_id)
            .execute()
        )

    restored = await as_owner.patch(f"/v1/hunts/{hunt_id}", json={"archived": False})
    assert restored.status_code == 200, restored.text
    assert restored.json()["archived_at"] is None
    renamed = await as_owner.patch(f"/v1/hunts/{hunt_id}", json={"name": "Restored"})
    assert renamed.status_code == 200, renamed.text


async def test_owner_can_permanently_delete_only_an_archived_hunt(
    as_owner: AsyncClient, db_pool, seeded_users
) -> None:
    hunt_id = await db_pool.fetchval(
        "insert into hunts(name, owner_id) values('Delete Me', $1) returning id",
        seeded_users["owner"].user_id,
    )
    active = await as_owner.request(
        "DELETE", f"/v1/hunts/{hunt_id}", json={"confirmation_name": "Delete Me"}
    )
    assert active.status_code == 409
    assert active.json()["code"] == "hunt_not_archived"

    assert (
        await as_owner.patch(f"/v1/hunts/{hunt_id}", json={"archived": True})
    ).status_code == 200
    impact = await as_owner.get(f"/v1/hunts/{hunt_id}/deletion-impact")
    assert impact.status_code == 200
    deleted = await as_owner.request(
        "DELETE", f"/v1/hunts/{hunt_id}", json={"confirmation_name": "Delete Me"}
    )
    assert deleted.status_code == 200, deleted.text
    assert not await db_pool.fetchval("select exists(select 1 from hunts where id=$1)", hunt_id)


async def test_site_admin_lock_blocks_members_and_admin_mutations_until_unlock(
    as_owner: AsyncClient, db_pool, lifecycle_hunt, seeded_users
) -> None:
    admin = seeded_users["outsider"]
    hunt_id = lifecycle_hunt["hunt_id"]
    await db_pool.execute(
        "insert into site_admins(user_id) values($1) on conflict do nothing", admin.user_id
    )
    app = create_app()
    app.state.db_pool = db_pool
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {admin.token}"},
        ) as admin_client:
            locked = await admin_client.put(
                f"/v1/admin/hunts/{hunt_id}/lock", json={"locked": True}
            )
            assert locked.status_code == 200, locked.text
            assert locked.json()["locked_at"] is not None

            archive = await as_owner.patch(f"/v1/hunts/{hunt_id}", json={"archived": True})
            assert archive.status_code == 423
            assert archive.json()["code"] == "hunt_locked"
            delete = await admin_client.request(
                "DELETE",
                f"/v1/admin/hunts/{hunt_id}",
                json={"confirmation_name": "Lifecycle Hunt"},
            )
            assert delete.status_code == 423

            unlocked = await admin_client.put(
                f"/v1/admin/hunts/{hunt_id}/lock", json={"locked": False}
            )
            assert unlocked.status_code == 200, unlocked.text
            assert unlocked.json()["locked_at"] is None
    finally:
        await db_pool.execute("delete from site_admins where user_id=$1", admin.user_id)
