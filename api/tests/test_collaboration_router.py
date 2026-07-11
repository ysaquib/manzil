from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_comment_create_and_author_soft_delete(
    collab_hunt, as_member: AsyncClient, as_curator: AsyncClient, db_pool
) -> None:
    listing_id = collab_hunt["member_listing_id"]
    created = await as_member.post(
        f"/v1/listings/{listing_id}/comments", json={"body": "Worth touring"}
    )
    assert created.status_code == 201
    comment_id = created.json()["id"]
    denied = await as_curator.delete(f"/v1/comments/{comment_id}")
    assert denied.status_code == 403
    deleted = await as_member.delete(f"/v1/comments/{comment_id}")
    assert deleted.status_code == 204
    assert await db_pool.fetchval(
        "select deleted_at is not null from comments where id = $1", UUID(comment_id)
    )


@pytest.mark.asyncio
async def test_rating_upsert_and_clear(collab_hunt, as_member: AsyncClient, db_pool) -> None:
    listing_id = collab_hunt["owner_listing_id"]
    rated = await as_member.put(f"/v1/listings/{listing_id}/rating", json={"rating": 4})
    assert rated.status_code == 200
    invalid = await as_member.put(f"/v1/listings/{listing_id}/rating", json={"rating": 6})
    assert invalid.status_code == 422
    cleared = await as_member.delete(f"/v1/listings/{listing_id}/rating")
    assert cleared.status_code == 204
    assert (
        await db_pool.fetchval(
            "select count(*) from ratings where hunt_listing_id = $1", UUID(listing_id)
        )
        == 0
    )


@pytest.mark.asyncio
async def test_member_color_accepts_token_and_canonicalizes_hex(
    collab_hunt, as_member: AsyncClient, seeded_users
) -> None:
    path = f"/v1/hunts/{collab_hunt['hunt_id']}/members/{seeded_users['member'].user_id}"
    token = await as_member.patch(path, json={"color": "moss"})
    assert token.status_code == 200
    assert token.json()["color"] == "moss"
    custom = await as_member.patch(path, json={"color": "#a1b2c3"})
    assert custom.status_code == 200
    assert custom.json()["color"] == "#A1B2C3"
    invalid = await as_member.patch(path, json={"color": "chartreuse"})
    assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_member_cannot_change_another_color(
    collab_hunt, as_member: AsyncClient, seeded_users
) -> None:
    response = await as_member.patch(
        f"/v1/hunts/{collab_hunt['hunt_id']}/members/{seeded_users['owner'].user_id}",
        json={"color": "plum"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "cannot_edit_member_color"


# --- P2-8: member management + ownership transfer ---


@pytest.mark.asyncio
async def test_list_members_visible_to_member_not_outsider(
    collab_hunt, as_member: AsyncClient, as_outsider: AsyncClient, seeded_users
) -> None:
    path = f"/v1/hunts/{collab_hunt['hunt_id']}/members"
    response = await as_member.get(path)
    assert response.status_code == 200
    rows = response.json()
    assert [r["role"] for r in rows] == ["owner", "curator", "member"]  # role-rank order
    assert {r["user_id"] for r in rows} == {
        seeded_users["owner"].user_id,
        seeded_users["curator"].user_id,
        seeded_users["member"].user_id,
    }
    outsider = await as_outsider.get(path)
    assert outsider.status_code == 404


@pytest.mark.asyncio
async def test_owner_promotes_and_demotes_member(
    collab_hunt, as_owner: AsyncClient, seeded_users
) -> None:
    path = f"/v1/hunts/{collab_hunt['hunt_id']}/members/{seeded_users['member'].user_id}"
    promoted = await as_owner.patch(path, json={"role": "curator"})
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "curator"
    demoted = await as_owner.patch(path, json={"role": "member"})
    assert demoted.status_code == 200
    assert demoted.json()["role"] == "member"


@pytest.mark.asyncio
async def test_role_patch_denied_cases(
    collab_hunt, as_owner: AsyncClient, as_member: AsyncClient, seeded_users
) -> None:
    hunt_id = collab_hunt["hunt_id"]
    member_path = f"/v1/hunts/{hunt_id}/members/{seeded_users['member'].user_id}"
    owner_path = f"/v1/hunts/{hunt_id}/members/{seeded_users['owner'].user_id}"

    self_role = await as_member.patch(member_path, json={"role": "curator"})
    assert self_role.status_code == 403
    assert self_role.json()["code"] == "cannot_change_own_role"

    owner_self_role = await as_owner.patch(owner_path, json={"role": "curator"})
    assert owner_self_role.status_code == 403
    assert owner_self_role.json()["code"] == "cannot_change_own_role"

    to_owner = await as_owner.patch(member_path, json={"role": "owner"})
    assert to_owner.status_code == 422  # Literal member|curator; transfer is the path

    others_color = await as_owner.patch(member_path, json={"color": "plum"})
    assert others_color.status_code == 403
    assert others_color.json()["code"] == "cannot_edit_member_color"


@pytest.mark.asyncio
async def test_self_display_name_patch_with_validation(
    collab_hunt, as_member: AsyncClient, seeded_users
) -> None:
    path = f"/v1/hunts/{collab_hunt['hunt_id']}/members/{seeded_users['member'].user_id}"
    ok = await as_member.patch(path, json={"display_name": "  Alice  "})
    assert ok.status_code == 200
    assert ok.json()["display_name"] == "Alice"  # trimmed
    blank = await as_member.patch(path, json={"display_name": "   "})
    assert blank.status_code == 422
    too_long = await as_member.patch(path, json={"display_name": "x" * 81})
    assert too_long.status_code == 422


@pytest.mark.asyncio
async def test_owner_removes_member_and_rls_hides_hunt(
    collab_hunt, as_owner: AsyncClient, seeded_users
) -> None:
    hunt_id = collab_hunt["hunt_id"]
    removed = await as_owner.delete(
        f"/v1/hunts/{hunt_id}/members/{seeded_users['member'].user_id}"
    )
    assert removed.status_code == 204
    # P2-8 done-when: the removed member no longer sees the hunt at the RLS layer.
    rows = (
        seeded_users["member"].supabase.table("hunts").select("id").eq("id", hunt_id).execute().data
        or []
    )
    assert rows == []


@pytest.mark.asyncio
async def test_delete_denied_cases(
    collab_hunt,
    as_owner: AsyncClient,
    as_curator: AsyncClient,
    as_member: AsyncClient,
    seeded_users,
) -> None:
    hunt_id = collab_hunt["hunt_id"]
    owner_id = seeded_users["owner"].user_id
    member_id = seeded_users["member"].user_id

    remove_owner = await as_owner.delete(f"/v1/hunts/{hunt_id}/members/{owner_id}")
    assert remove_owner.status_code == 403
    assert remove_owner.json()["code"] == "cannot_remove_owner"

    by_curator = await as_curator.delete(f"/v1/hunts/{hunt_id}/members/{member_id}")
    assert by_curator.status_code == 403
    assert by_curator.json()["code"] == "insufficient_role"

    by_member = await as_member.delete(f"/v1/hunts/{hunt_id}/members/{owner_id}")
    assert by_member.status_code == 403
    assert by_member.json()["code"] == "insufficient_role"


@pytest.mark.asyncio
async def test_transfer_ownership_end_to_end(
    collab_hunt, as_owner: AsyncClient, as_member: AsyncClient, db_pool, seeded_users
) -> None:
    hunt_id = collab_hunt["hunt_id"]
    old_owner = seeded_users["owner"].user_id
    new_owner = seeded_users["member"].user_id

    transferred = await as_owner.post(
        f"/v1/hunts/{hunt_id}/transfer-ownership", json={"new_owner_id": new_owner}
    )
    assert transferred.status_code == 200
    assert transferred.json()["status"] == "ok"

    roles = {
        r["user_id"]: r["role"]
        for r in await db_pool.fetch(
            "select user_id::text, role from hunt_members where hunt_id = $1", UUID(hunt_id)
        )
    }
    assert roles[old_owner] == "curator"
    assert roles[new_owner] == "owner"

    # Owner-only route: old owner (now curator) is refused, new owner passes.
    old_owner_edit = await as_owner.patch(f"/v1/hunts/{hunt_id}", json={"name": "Nope"})
    assert old_owner_edit.status_code == 403
    new_owner_edit = await as_member.patch(f"/v1/hunts/{hunt_id}", json={"name": "Yes"})
    assert new_owner_edit.status_code == 200


@pytest.mark.asyncio
async def test_transfer_ownership_edge_cases(
    collab_hunt,
    as_owner: AsyncClient,
    as_member: AsyncClient,
    seeded_users,
) -> None:
    hunt_id = collab_hunt["hunt_id"]

    non_member = await as_owner.post(
        f"/v1/hunts/{hunt_id}/transfer-ownership",
        json={"new_owner_id": seeded_users["outsider"].user_id},
    )
    assert non_member.status_code == 404
    assert non_member.json()["code"] == "transfer_target_not_member"

    by_non_owner = await as_member.post(
        f"/v1/hunts/{hunt_id}/transfer-ownership",
        json={"new_owner_id": seeded_users["member"].user_id},
    )
    assert by_non_owner.status_code == 403
    assert by_non_owner.json()["code"] == "insufficient_role"

    idempotent = await as_owner.post(
        f"/v1/hunts/{hunt_id}/transfer-ownership",
        json={"new_owner_id": seeded_users["owner"].user_id},
    )
    assert idempotent.status_code == 200
    assert idempotent.json()["status"] == "ok"
