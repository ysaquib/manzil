"""AD-F: the hunt activity feed, and the Site Admin identity it rests on.

The feed has no backing table. Its raw union is a grantless private view;
Owners cross the boundary through a bounded RPC, while Site Admins cross it
through the separately authenticated admin API. These tests pin both the data
shape and that separation so a convenience grant cannot recreate the original
cross-tenant footgun.
"""

from __future__ import annotations

import pytest
from postgrest.exceptions import APIError

pytestmark = pytest.mark.asyncio


async def _seed_activity(db_pool, collab_hunt) -> None:
    """One event of each shape the feed unions."""
    listing = collab_hunt["owner_listing_id"]
    await db_pool.execute(
        "insert into fee_checklist (hunt_listing_id, fee_slot, amount, value_state) "
        "values ($1, 'broker', 1200, 'manual')",
        listing,
    )
    await db_pool.execute("update hunt_listings set status = 'archived' where id = $1", listing)


def _activity(user, hunt_id, *, limit=100, before=None):
    params = {"p_hunt_id": str(hunt_id), "p_limit": limit}
    if before is not None:
        params["p_before"] = before
    return user.supabase.rpc("get_hunt_activity", params).execute()


async def test_owner_sees_the_feed_and_other_roles_are_refused(
    db_pool, collab_hunt, seeded_users
) -> None:
    await _seed_activity(db_pool, collab_hunt)
    hunt_id = str(collab_hunt["hunt_id"])

    owner_feed = _activity(seeded_users["owner"], hunt_id)
    kinds = {row["kind"] for row in owner_feed.data}
    assert "fee_set" in kinds
    assert "listing_curated" in kinds
    assert "member_joined" in kinds

    first_page = _activity(seeded_users["owner"], hunt_id, limit=1)
    assert len(first_page.data) == 1
    older_page = _activity(seeded_users["owner"], hunt_id, before=first_page.data[0]["occurred_at"])
    assert all(row["occurred_at"] < first_page.data[0]["occurred_at"] for row in older_page.data)

    # Refusal is preferable to an empty result: callers cannot mistake missing
    # authorization for a Hunt with no history.
    for role in ("curator", "member", "outsider"):
        with pytest.raises(APIError) as excinfo:
            _activity(seeded_users[role], hunt_id)
        assert excinfo.value.code == "42501", f"{role} must be rejected by the Owner gate"


async def test_the_feed_never_crosses_hunts(db_pool, collab_hunt, seeded_users) -> None:
    """The gate gets no second chance: a view without it leaks every Hunt at
    once, so this asserts the negative directly rather than trusting the join."""
    await _seed_activity(db_pool, collab_hunt)
    other_hunt = await db_pool.fetchval(
        "insert into hunts (name, owner_id) values ('Someone Else', $1) returning id",
        seeded_users["outsider"].user_id,
    )
    try:
        rows = _activity(seeded_users["owner"], collab_hunt["hunt_id"])
        assert rows.data, "the owner should still see their own Hunt"
        assert all(row["hunt_id"] == str(collab_hunt["hunt_id"]) for row in rows.data)

        with pytest.raises(APIError) as excinfo:
            _activity(seeded_users["owner"], other_hunt)
        assert excinfo.value.code == "42501"
    finally:
        await db_pool.execute("delete from hunts where id = $1", other_hunt)
        await db_pool.execute("delete from deletion_tombstones where hunt_id = $1", other_hunt)


async def test_site_admin_access_is_not_smuggled_through_the_owner_rpc(
    db_pool, collab_hunt, seeded_users
) -> None:
    """Admin access belongs to the AdminUser-gated service route, not a public
    JWT-callable function that could drift from that route's audit boundary."""
    await _seed_activity(db_pool, collab_hunt)
    outsider = seeded_users["outsider"]
    hunt_id = str(collab_hunt["hunt_id"])

    await db_pool.execute("insert into site_admins (user_id) values ($1)", outsider.user_id)
    try:
        with pytest.raises(APIError) as excinfo:
            _activity(outsider, hunt_id)
        assert excinfo.value.code == "42501"

        # This is the exact query used by the already AdminUser-gated API route.
        rows = await db_pool.fetch(
            "select * from private.hunt_activity_all where hunt_id = $1",
            collab_hunt["hunt_id"],
        )
        assert rows, "the privileged admin path can read the internal union"

        membership = await db_pool.fetchval(
            "select count(*) from hunt_members where hunt_id = $1 and user_id = $2",
            collab_hunt["hunt_id"],
            outsider.user_id,
        )
        assert membership == 0
    finally:
        await db_pool.execute("delete from site_admins where user_id = $1", outsider.user_id)


async def test_visit_entries_are_absent_by_design(db_pool, collab_hunt, seeded_users) -> None:
    """A tour is 248 questions answered by named people. The feed reports that a
    tour happened and what came out of it, never how each person filled it in —
    §9.7 averages per member precisely so no one's volume dominates."""
    hunt_id = str(collab_hunt["hunt_id"])
    feed = _activity(seeded_users["owner"], hunt_id)
    assert all(row["kind"] != "visit_entry" for row in feed.data)


async def test_raw_union_is_private_and_the_owner_rpc_has_narrow_grants(db_pool) -> None:
    assert await db_pool.fetchval("select to_regclass('public.hunt_activity')") is None
    assert not await db_pool.fetchval(
        "select has_table_privilege('anon', 'private.hunt_activity_all', 'select')"
    )
    assert not await db_pool.fetchval(
        "select has_table_privilege('authenticated', 'private.hunt_activity_all', 'select')"
    )
    assert await db_pool.fetchval(
        "select 'security_barrier=true' = any(coalesce(c.reloptions, array[]::text[])) "
        "from pg_class c join pg_namespace n on n.oid = c.relnamespace "
        "where n.nspname = 'private' and c.relname = 'hunt_activity_all'"
    )
    assert not await db_pool.fetchval(
        "select has_function_privilege('anon', "
        "'public.get_hunt_activity(uuid,integer,timestamp with time zone)', 'execute')"
    )
    assert await db_pool.fetchval(
        "select has_function_privilege('authenticated', "
        "'public.get_hunt_activity(uuid,integer,timestamp with time zone)', 'execute')"
    )


# ── the primordial admin ─────────────────────────────────────────────────────


async def test_the_first_admin_cannot_be_revoked_by_anyone(
    db_pool, seeded_users, no_primordial_admin
) -> None:
    """A trigger, not a policy: `service_role` bypasses RLS and is exactly what
    the admin router runs as, so a policy would guard everyone except the one
    caller able to do the damage. This runs as the table owner — the most
    privileged caller there is — and must still fail."""
    user_id = seeded_users["outsider"].user_id
    await db_pool.execute(
        "insert into site_admins (user_id, is_primordial) values ($1, true)", user_id
    )
    try:
        with pytest.raises(Exception, match="primordial site admin cannot be revoked"):
            await db_pool.execute("delete from site_admins where user_id = $1", user_id)

        # Clearing the flag would otherwise be a two-step delete.
        with pytest.raises(Exception, match="is_primordial is immutable"):
            await db_pool.execute(
                "update site_admins set is_primordial = false where user_id = $1", user_id
            )

        assert await db_pool.fetchval("select count(*) from site_admins where is_primordial") == 1
    finally:
        await db_pool.execute(
            "alter table site_admins disable trigger site_admins_protect_primordial"
        )
        await db_pool.execute("delete from site_admins where user_id = $1", user_id)
        await db_pool.execute(
            "alter table site_admins enable trigger site_admins_protect_primordial"
        )


async def test_only_one_primordial_admin_may_exist(
    db_pool, seeded_users, no_primordial_admin
) -> None:
    first, second = seeded_users["outsider"].user_id, seeded_users["curator"].user_id
    await db_pool.execute(
        "insert into site_admins (user_id, is_primordial) values ($1, true)", first
    )
    try:
        with pytest.raises(Exception):  # noqa: B017 - asyncpg raises its own unique-violation type
            await db_pool.execute(
                "insert into site_admins (user_id, is_primordial) values ($1, true)", second
            )
    finally:
        await db_pool.execute(
            "alter table site_admins disable trigger site_admins_protect_primordial"
        )
        await db_pool.execute(
            "delete from site_admins where user_id = any($1::uuid[])", [first, second]
        )
        await db_pool.execute(
            "alter table site_admins enable trigger site_admins_protect_primordial"
        )


async def test_clients_cannot_read_or_write_the_admin_roster(seeded_users) -> None:
    """`site_admins` has RLS on and no policies at all, so an ordinary account
    cannot discover who the administrators are."""
    result = seeded_users["owner"].supabase.table("site_admins").select("*").execute()
    assert result.data == []

    with pytest.raises(Exception):  # noqa: B017 - PostgREST surfaces its own error type
        seeded_users["owner"].supabase.table("site_admins").insert(
            {"user_id": seeded_users["owner"].user_id}
        ).execute()
