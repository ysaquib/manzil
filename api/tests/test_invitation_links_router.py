from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_link_defaults_join_and_existing_member_does_not_consume(
    collab_hunt,
    as_owner: AsyncClient,
    as_outsider: AsyncClient,
    as_member: AsyncClient,
    db_pool,
    seeded_users,
) -> None:
    path = f"/v1/hunts/{collab_hunt['hunt_id']}/invitation-links"
    created = await as_owner.post(path, json={})
    assert created.status_code == 201
    body = created.json()
    assert body["max_uses"] is None
    assert body["name"] is None
    assert body["status"] == "active"
    assert body["use_count"] == 0
    token = body["link"].rsplit("/", 1)[-1]

    existing = await as_member.post(f"/v1/invitation-links/{token}/join")
    assert existing.status_code == 200
    assert (await as_owner.get(path)).json()[0]["use_count"] == 0

    joined = await as_outsider.post(f"/v1/invitation-links/{token}/join")
    assert joined.status_code == 200
    member = await db_pool.fetchrow(
        "select role, color from hunt_members where hunt_id = $1 and user_id = $2",
        UUID(collab_hunt["hunt_id"]),
        seeded_users["outsider"].user_id,
    )
    assert dict(member) == {"role": "member", "color": "dusk"}
    listed = (await as_owner.get(path)).json()[0]
    assert listed["use_count"] == 1
    assert listed["joins"][0]["user_id"] == seeded_users["outsider"].user_id


@pytest.mark.asyncio
async def test_limit_edit_exhausts_and_reactivates_link(
    collab_hunt, as_owner: AsyncClient, as_outsider: AsyncClient
) -> None:
    collection = f"/v1/hunts/{collab_hunt['hunt_id']}/invitation-links"
    created = await as_owner.post(collection, json={"max_uses": 1})
    link = created.json()
    token = link["link"].rsplit("/", 1)[-1]
    assert (await as_outsider.post(f"/v1/invitation-links/{token}/join")).status_code == 200

    exhausted = await as_owner.get(collection)
    assert exhausted.json()[0]["status"] == "exhausted"
    raised = await as_owner.patch(f"/v1/invitation-links/{link['id']}", json={"max_uses": 2})
    assert raised.status_code == 200
    assert raised.json()["status"] == "active"


@pytest.mark.asyncio
async def test_expired_and_soft_deleted_links_are_specific_and_hidden(
    collab_hunt, as_owner: AsyncClient, as_outsider: AsyncClient, db_pool
) -> None:
    collection = f"/v1/hunts/{collab_hunt['hunt_id']}/invitation-links"
    expired = await as_owner.post(
        collection, json={"expires_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat()}
    )
    expired_token = expired.json()["link"].rsplit("/", 1)[-1]
    refused = await as_outsider.post(f"/v1/invitation-links/{expired_token}/join")
    assert refused.status_code == 410
    assert refused.json()["code"] == "invitation_link_expired"

    active = await as_owner.post(collection, json={})
    active_body = active.json()
    active_token = active_body["link"].rsplit("/", 1)[-1]
    deleted = await as_owner.delete(f"/v1/invitation-links/{active_body['id']}")
    assert deleted.status_code == 204
    refused = await as_outsider.post(f"/v1/invitation-links/{active_token}/join")
    assert refused.status_code == 410
    assert refused.json()["code"] == "invitation_link_deleted"
    assert all(row["id"] != active_body["id"] for row in (await as_owner.get(collection)).json())
    persisted = await db_pool.fetchval(
        "select deleted_at is not null from invitation_links where id = $1",
        UUID(active_body["id"]),
    )
    assert persisted is True


@pytest.mark.asyncio
async def test_only_owner_can_manage_links(
    collab_hunt, as_member: AsyncClient, as_curator: AsyncClient, as_outsider: AsyncClient
) -> None:
    path = f"/v1/hunts/{collab_hunt['hunt_id']}/invitation-links"
    for client in (as_member, as_curator, as_outsider):
        assert (await client.get(path)).status_code in {403, 404}
        assert (await client.post(path, json={})).status_code in {403, 404}


@pytest.mark.asyncio
async def test_invitation_link_name_create_patch_and_validation(
    collab_hunt, as_owner: AsyncClient
) -> None:
    collection = f"/v1/hunts/{collab_hunt['hunt_id']}/invitation-links"

    named = await as_owner.post(collection, json={"name": "  Family link  "})
    assert named.status_code == 201
    named_body = named.json()
    assert named_body["name"] == "Family link"

    blank = await as_owner.post(collection, json={"name": "   "})
    assert blank.status_code == 201
    assert blank.json()["name"] is None

    omitted = await as_owner.post(collection, json={})
    assert omitted.status_code == 201
    assert omitted.json()["name"] is None

    renamed = await as_owner.patch(
        f"/v1/invitation-links/{named_body['id']}",
        json={"name": " Weekend guests "},
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Weekend guests"

    cleared = await as_owner.patch(
        f"/v1/invitation-links/{named_body['id']}",
        json={"name": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["name"] is None

    too_long = await as_owner.post(collection, json={"name": "x" * 81})
    assert too_long.status_code == 422
