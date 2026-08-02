"""AD-G: the four places history used to die (DESIGN §20 v3.38).

Everything here is enforced by trigger rather than by a writer, so these tests
mutate the tables directly: the API, the worker and a raw PostgREST call all
reach the same rows, and a trigger is the only place that sees all three. If
these pass for a direct write they pass for every caller.

The line on visibility is deliberate and is asserted below: **data provenance
is shared with members, governance history belongs to the Owner.**
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

pytestmark = pytest.mark.asyncio


# ── 1. fee history ───────────────────────────────────────────────────────────


async def test_fee_edits_leave_a_trail_and_no_op_saves_do_not(db_pool, collab_hunt) -> None:
    """A fee moving 1800 -> 0 changes all-in cost and therefore the score. The
    old value and its author used to be destroyed by the upsert."""
    listing = collab_hunt["owner_listing_id"]
    await db_pool.execute(
        "insert into fee_checklist (hunt_listing_id, fee_slot, amount, value_state, entered_by) "
        "values ($1, 'broker', 1800, 'manual', $2)",
        listing,
        uuid4(),
    )
    await db_pool.execute(
        "update fee_checklist set amount = 0 where hunt_listing_id = $1 and fee_slot = 'broker'",
        listing,
    )
    # The fee writer touches updated_at on every save; an unchanged save must not
    # bury the real edits under noise.
    await db_pool.execute(
        "update fee_checklist set updated_at = now() "
        "where hunt_listing_id = $1 and fee_slot = 'broker'",
        listing,
    )

    trail = await db_pool.fetch(
        "select amount from fee_checklist_history "
        "where hunt_listing_id = $1 and fee_slot = 'broker' order by recorded_at",
        listing,
    )
    assert [float(row["amount"]) for row in trail] == [1800.0, 0.0]


# ── 2. membership history ────────────────────────────────────────────────────


async def test_role_changes_are_recorded_and_cosmetic_edits_are_not(
    db_pool, collab_hunt, seeded_users
) -> None:
    hunt_id = collab_hunt["hunt_id"]
    member = seeded_users["member"]

    await db_pool.execute(
        "update hunt_members set role = 'curator' where hunt_id = $1 and user_id = $2",
        hunt_id,
        member.user_id,
    )
    await db_pool.execute(
        "update hunt_members set color = 'moss' where hunt_id = $1 and user_id = $2",
        hunt_id,
        member.user_id,
    )

    trail = await db_pool.fetch(
        "select action, role from hunt_member_history "
        "where hunt_id = $1 and user_id = $2 order by recorded_at",
        hunt_id,
        member.user_id,
    )
    assert [(row["action"], row["role"]) for row in trail] == [
        ("joined", "member"),
        ("role_changed", "curator"),
    ]


async def test_removing_a_member_records_a_departure(db_pool, collab_hunt, seeded_users) -> None:
    hunt_id = collab_hunt["hunt_id"]
    curator = seeded_users["curator"]
    await db_pool.execute(
        "delete from hunt_members where hunt_id = $1 and user_id = $2", hunt_id, curator.user_id
    )

    last = await db_pool.fetchrow(
        "select action, role from hunt_member_history "
        "where hunt_id = $1 and user_id = $2 order by recorded_at desc limit 1",
        hunt_id,
        curator.user_id,
    )
    assert last["action"] == "left"
    assert last["role"] is None  # null role == the membership ended


# ── 3. listing curation history ──────────────────────────────────────────────


async def test_archiving_and_policy_changes_are_recorded(db_pool, collab_hunt) -> None:
    listing = collab_hunt["owner_listing_id"]
    await db_pool.execute("update hunt_listings set status = 'archived' where id = $1", listing)
    await db_pool.execute("update hunt_listings set status = 'archived' where id = $1", listing)
    await db_pool.execute(
        "update hunt_listings set source_policy = 'tier_1' where id = $1", listing
    )

    trail = await db_pool.fetch(
        "select status, source_policy from hunt_listing_history "
        "where hunt_listing_id = $1 order by recorded_at",
        listing,
    )
    assert [(row["status"], row["source_policy"]) for row in trail] == [
        ("archived", "tiers_1_2_3"),
        ("archived", "tier_1"),
    ]


# ── 4. tombstones ────────────────────────────────────────────────────────────


async def test_deleting_a_hunt_leaves_a_tombstone_for_everything_it_took(
    db_pool, seeded_users
) -> None:
    """The hazard this covers: a tombstone with a foreign key to its own subject
    cascades away with it and records nothing. These tables carry no FKs, and a
    membership row dying inside a Hunt cascade must not try to write history
    whose parent Hunt is already gone."""
    owner = seeded_users["owner"]
    hunt_id = await db_pool.fetchval(
        "insert into hunts (name, owner_id) values ('Doomed Hunt', $1) returning id",
        owner.user_id,
    )
    property_id = await db_pool.fetchval(
        "insert into properties (name, canonical_address) "
        "values ('Doomed Property', '9 Gone St') returning id"
    )
    await db_pool.execute(
        "insert into hunt_listings (hunt_id, property_id, added_by) values ($1, $2, $3)",
        hunt_id,
        property_id,
        owner.user_id,
    )

    try:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)

        stones = await db_pool.fetch(
            "select entity_type, label, via_cascade, detail from deletion_tombstones "
            "where hunt_id = $1 order by entity_type",
            hunt_id,
        )
        by_type = {row["entity_type"]: row for row in stones}

        # The Hunt itself died directly; everything under it died with it, and
        # says so — one deletion collapses to one line in a reader.
        assert by_type["hunt"]["label"] == "Doomed Hunt"
        assert by_type["hunt"]["via_cascade"] is False
        assert by_type["hunt_listing"]["label"] == "Doomed Property"
        assert by_type["hunt_listing"]["via_cascade"] is True
        assert by_type["hunt_member"]["via_cascade"] is True
        assert json.loads(by_type["hunt_member"]["detail"])["role"] == "owner"

        # The tombstone outlives its subject: no FK dragged it away.
        assert await db_pool.fetchval("select count(*) from hunts where id = $1", hunt_id) == 0
        assert len(stones) == 3
    finally:
        await db_pool.execute("delete from deletion_tombstones where hunt_id = $1", hunt_id)
        await db_pool.execute("delete from properties where id = $1", property_id)


# ── visibility ───────────────────────────────────────────────────────────────


async def test_members_see_fee_provenance_but_not_governance_history(
    db_pool, collab_hunt, seeded_users
) -> None:
    """Any member may ask who zeroed a fee — it is their shared Listing and it
    moves their score. Who demoted whom is a decision about the Hunt, and it
    belongs to the Owner (and, from AD-1, a site admin)."""
    listing = collab_hunt["owner_listing_id"]
    hunt_id = collab_hunt["hunt_id"]
    await db_pool.execute(
        "insert into fee_checklist (hunt_listing_id, fee_slot, amount, value_state) "
        "values ($1, 'application', 75, 'manual')",
        listing,
    )

    supabase = seeded_users["member"].supabase

    visible = supabase.table("fee_checklist_history").select("*").execute()
    assert any(row["hunt_listing_id"] == str(listing) for row in visible.data)

    governance = (
        supabase.table("hunt_member_history").select("*").eq("hunt_id", str(hunt_id)).execute()
    )
    assert governance.data == []

    tombstones = supabase.table("deletion_tombstones").select("*").execute()
    assert tombstones.data == []


async def test_owner_sees_governance_history(collab_hunt, seeded_users) -> None:
    hunt_id = collab_hunt["hunt_id"]
    supabase = seeded_users["owner"].supabase

    governance = (
        supabase.table("hunt_member_history").select("*").eq("hunt_id", str(hunt_id)).execute()
    )
    assert len(governance.data) >= 1


async def test_history_is_append_only_for_clients(collab_hunt, seeded_users) -> None:
    """No client write policy exists on any of these: every row comes from a
    SECURITY DEFINER trigger. A history row a member could forge is worthless."""
    supabase = seeded_users["owner"].supabase
    with pytest.raises(Exception):  # noqa: B017 - PostgREST surfaces its own error type
        supabase.table("hunt_member_history").insert(
            {
                "hunt_id": str(collab_hunt["hunt_id"]),
                "user_id": str(uuid4()),
                "role": "owner",
                "action": "joined",
            }
        ).execute()
