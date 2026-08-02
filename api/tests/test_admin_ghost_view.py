"""AD-4: the ghost view's database half (DESIGN §20 v3.43).

The read predicate is the one change in this workstream that touches policies
protecting every Hunt in the system, so the tests are deliberately lopsided:
a little on "an admin can read", and a lot on "an admin still cannot write".

The asymmetry *is* the design. A Site Admin who could write through PostgREST
would be a Site Admin whose writes never reach `admin_audit_log`, which is the
entire reason the admin router exists.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

pytestmark = pytest.mark.asyncio

# Every Hunt-scoped table a ghost is expected to be able to read.
READABLE = [
    "hunts",
    "hunt_members",
    "hunt_listings",
    "rubric_criteria",
    "scores",
    "overrides",
    "comments",
    "ratings",
    "fee_checklist",
    "jobs",
    "job_events",
    "visits",
    "visit_units",
    "visit_entries",
]


@pytest.fixture
def ghost(seeded_users):  # type: ignore[no-untyped-def]
    """`outsider` is a member of nothing, so anything it can see it can only see
    because it is an admin."""
    return seeded_users["outsider"]


async def _grant(db_pool, user_id) -> None:
    await db_pool.execute(
        "insert into site_admins (user_id) values ($1) on conflict do nothing", user_id
    )


async def _revoke(db_pool, user_id) -> None:
    await db_pool.execute("delete from site_admins where user_id = $1", user_id)


# ── reads ────────────────────────────────────────────────────────────────────


async def test_a_non_member_sees_nothing_until_they_are_an_admin(
    db_pool, collab_hunt, ghost
) -> None:
    """The before/after that proves the predicate is doing the work, rather than
    the fixture happening to be permissive."""
    hunt_id = str(collab_hunt["hunt_id"])

    before = ghost.supabase.table("hunts").select("id").eq("id", hunt_id).execute()
    assert before.data == []

    await _grant(db_pool, ghost.user_id)
    try:
        after = ghost.supabase.table("hunts").select("id").eq("id", hunt_id).execute()
        assert [row["id"] for row in after.data] == [hunt_id]
    finally:
        await _revoke(db_pool, ghost.user_id)


async def test_the_predicate_reaches_every_hunt_scoped_table(
    db_pool, collab_hunt, ghost
) -> None:
    """A table that forgot the predicate shows up as one silently empty section
    in the panel — which nobody notices until support needs it."""
    await _grant(db_pool, ghost.user_id)
    try:
        for table in READABLE:
            result = ghost.supabase.table(table).select("*").limit(1).execute()
            assert isinstance(result.data, list), f"{table} did not answer"
    finally:
        await _revoke(db_pool, ghost.user_id)


async def test_an_admin_reads_a_tour_they_did_not_attend(
    db_pool, collab_hunt, ghost, seeded_users
) -> None:
    visit_id = await db_pool.fetchval(
        "insert into visits (hunt_id, property_id, created_by, template_version) "
        "values ($1, $2, $3, 1) returning id",
        collab_hunt["hunt_id"],
        collab_hunt["owner_property_id"],
        seeded_users["owner"].user_id,
    )
    try:
        await _grant(db_pool, ghost.user_id)
        visible = ghost.supabase.table("visits").select("id").eq("id", str(visit_id)).execute()
        assert [row["id"] for row in visible.data] == [str(visit_id)]
    finally:
        await _revoke(db_pool, ghost.user_id)
        await db_pool.execute("delete from visits where id = $1", visit_id)


# ── writes: the half that must NOT have widened ──────────────────────────────


async def test_an_admin_cannot_answer_a_visit_entry(
    db_pool, collab_hunt, ghost, seeded_users
) -> None:
    """§4.2's sharpest rule. An Entry feeds the per-member roll-up in §9.7, so a
    ghost answering a tour they did not attend corrupts a number nobody would
    think to distrust. The UI hides the control; this is what actually stops it."""
    visit_id = await db_pool.fetchval(
        "insert into visits (hunt_id, property_id, created_by, started_at, template_version) "
        "values ($1, $2, $3, now(), 1) returning id",
        collab_hunt["hunt_id"],
        collab_hunt["owner_property_id"],
        seeded_users["owner"].user_id,
    )
    try:
        await _grant(db_pool, ghost.user_id)

        # They can read the tour...
        assert ghost.supabase.table("visits").select("id").eq("id", str(visit_id)).execute().data

        # ...and cannot write to it.
        with pytest.raises(Exception):  # noqa: B017 - PostgREST raises its own type
            ghost.supabase.table("visit_entries").insert(
                {
                    "visit_id": str(visit_id),
                    "item_key": "prep_reviews",
                    "is_custom": False,
                    "author_user_id": ghost.user_id,
                    "value": {"text": "written by a ghost"},
                }
            ).execute()

        assert await db_pool.fetchval(
            "select count(*) from visit_entries where visit_id = $1", visit_id
        ) == 0
    finally:
        await _revoke(db_pool, ghost.user_id)
        await db_pool.execute("delete from visits where id = $1", visit_id)


async def test_an_admin_cannot_write_through_postgrest_at_all(
    db_pool, collab_hunt, ghost
) -> None:
    """If any of these succeeded, an admin could change a Hunt without the
    action ever reaching `admin_audit_log`."""
    await _grant(db_pool, ghost.user_id)
    try:
        listing_id = str(collab_hunt["owner_listing_id"])

        with pytest.raises(Exception):  # noqa: B017
            ghost.supabase.table("overrides").insert(
                {
                    "hunt_listing_id": listing_id,
                    "criterion_key": "beds",
                    "value": 99,
                    "user_id": ghost.user_id,
                }
            ).execute()

        with pytest.raises(Exception):  # noqa: B017
            ghost.supabase.table("comments").insert(
                {"hunt_listing_id": listing_id, "user_id": ghost.user_id, "body": "ghost"}
            ).execute()

        with pytest.raises(Exception):  # noqa: B017
            ghost.supabase.table("hunt_members").insert(
                {
                    "hunt_id": str(collab_hunt["hunt_id"]),
                    "user_id": ghost.user_id,
                    "role": "owner",
                }
            ).execute()

        # A read-modify-write is refused as well: the update policy never saw
        # the predicate, so there is no row the ghost is allowed to change.
        updated = (
            ghost.supabase.table("hunt_listings")
            .update({"status": "archived"})
            .eq("id", listing_id)
            .execute()
        )
        assert updated.data == []
        assert await db_pool.fetchval(
            "select status from hunt_listings where id = $1", collab_hunt["owner_listing_id"]
        ) == "active"
    finally:
        await _revoke(db_pool, ghost.user_id)


async def test_an_admin_does_not_become_a_member(db_pool, collab_hunt, ghost) -> None:
    """`member_role()` was deliberately left alone. An admin who started looking
    like a member would appear in the member list and satisfy the write
    policies — the two things §4.2 says must not happen."""
    await _grant(db_pool, ghost.user_id)
    try:
        role = await db_pool.fetchval(
            "select private.member_role($1)", collab_hunt["hunt_id"]
        )
        assert role is None

        members = (
            ghost.supabase.table("hunt_members")
            .select("user_id")
            .eq("hunt_id", str(collab_hunt["hunt_id"]))
            .execute()
        )
        # They can read the list — and are not on it.
        assert members.data
        assert all(row["user_id"] != ghost.user_id for row in members.data)
    finally:
        await _revoke(db_pool, ghost.user_id)


async def test_an_ordinary_member_is_unaffected_by_the_predicate(
    db_pool, collab_hunt, seeded_users
) -> None:
    """The regression this guards: widening reads must not have widened them for
    anyone who is not an admin."""
    other_hunt = await db_pool.fetchval(
        "insert into hunts (name, owner_id) values ('Not Theirs', $1) returning id", uuid4()
    )
    try:
        visible = (
            seeded_users["member"].supabase.table("hunts")
            .select("id")
            .eq("id", str(other_hunt))
            .execute()
        )
        assert visible.data == []
    finally:
        await db_pool.execute("delete from hunts where id = $1", other_hunt)
        await db_pool.execute("delete from deletion_tombstones where hunt_id = $1", other_hunt)
