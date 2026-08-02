"""AD-F: the hunt activity feed, and the Site Admin identity it rests on.

The feed has no backing table — it is a view over domain tables that were
already append-only — so these tests are about its *definition* and its
*gate*, not about any route.

The gate is the interesting part. `hunt_activity` is deliberately not a
`security_invoker` view: a non-member Site Admin would be filtered out by the
base tables' member-scoped policies and see an empty feed. Access therefore
lives in the view's own WHERE clause, which makes it the single thing standing
between one Hunt's history and another's.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

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


async def test_owner_sees_the_feed_and_other_roles_see_nothing(
    db_pool, collab_hunt, seeded_users
) -> None:
    await _seed_activity(db_pool, collab_hunt)
    hunt_id = str(collab_hunt["hunt_id"])

    owner_feed = (
        seeded_users["owner"].supabase.table("hunt_activity")
        .select("*")
        .eq("hunt_id", hunt_id)
        .execute()
    )
    kinds = {row["kind"] for row in owner_feed.data}
    assert "fee_set" in kinds
    assert "listing_curated" in kinds
    assert "member_joined" in kinds

    # A curator and a member are inside the Hunt and can see plenty elsewhere —
    # the feed is still not theirs.
    for role in ("curator", "member", "outsider"):
        feed = (
            seeded_users[role].supabase.table("hunt_activity")
            .select("*")
            .eq("hunt_id", hunt_id)
            .execute()
        )
        assert feed.data == [], f"{role} must not read the activity feed"


async def test_the_feed_never_crosses_hunts(db_pool, collab_hunt, seeded_users) -> None:
    """The gate gets no second chance: a view without it leaks every Hunt at
    once, so this asserts the negative directly rather than trusting the join."""
    await _seed_activity(db_pool, collab_hunt)
    other_hunt = await db_pool.fetchval(
        "insert into hunts (name, owner_id) values ('Someone Else', $1) returning id",
        uuid4(),
    )
    try:
        rows = (
            seeded_users["owner"].supabase.table("hunt_activity")
            .select("hunt_id")
            .execute()
        )
        assert all(row["hunt_id"] != str(other_hunt) for row in rows.data)
        assert rows.data, "the owner should still see their own Hunt"
    finally:
        await db_pool.execute("delete from hunts where id = $1", other_hunt)
        await db_pool.execute("delete from deletion_tombstones where hunt_id = $1", other_hunt)


async def test_a_site_admin_reads_a_hunt_they_do_not_belong_to(
    db_pool, collab_hunt, seeded_users
) -> None:
    """The requirement the security_invoker option could not satisfy: an admin
    with no membership anywhere still reads the feed."""
    await _seed_activity(db_pool, collab_hunt)
    outsider = seeded_users["outsider"]
    hunt_id = str(collab_hunt["hunt_id"])

    before = (
        outsider.supabase.table("hunt_activity").select("*").eq("hunt_id", hunt_id).execute()
    )
    assert before.data == []

    await db_pool.execute("insert into site_admins (user_id) values ($1)", outsider.user_id)
    try:
        after = (
            outsider.supabase.table("hunt_activity").select("*").eq("hunt_id", hunt_id).execute()
        )
        assert after.data, "a site admin sees the feed of a Hunt they are not in"
        # ...without having become a member of it.
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
    feed = (
        seeded_users["owner"].supabase.table("hunt_activity")
        .select("kind")
        .eq("hunt_id", hunt_id)
        .execute()
    )
    assert all(row["kind"] != "visit_entry" for row in feed.data)


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
