"""DM-1/DM-3/DM-4: the Demo Account is read-only, and confined (DESIGN §16).

These run against the database rather than the API on purpose. A demo visitor
holds a real Supabase session in a browser we do not control, so the threat
model is a JWT driven straight at PostgREST with FastAPI bypassed entirely --
which means an API-level test proves nothing about any claim on this page.
Everything here writes directly, exactly as a hostile client would.

The coverage tests are the load-bearing ones. Each migration in this series
carries its own self-check, but a migration's check runs at that migration's
point in history and therefore cannot see a table introduced by a *later* one.
These do: they run against the schema as it finally stands, so a table added
next month without the guard fails here.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import UUID

import asyncpg
import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def demo_conn(db_pool, seeded_users) -> AsyncIterator[tuple]:
    """A connection inside a transaction where `outsider` is a Demo Account.

    Rolled back unconditionally, so the local database is left untouched even
    when an assertion fails mid-test.

    Request this fixture **after** `collab_hunt` in a test signature, never
    before. Pytest tears function-scoped fixtures down in reverse order of
    setup, and this one holds an open transaction touching `hunt_members`; if it
    is set up first it is torn down last, and `collab_hunt`'s `delete from
    hunts` blocks on locks this transaction still holds. That deadlock hangs
    until something is killed rather than failing, which is exactly the failure
    mode the statement timeout below turns into an error.
    """
    user_id = seeded_users["outsider"].user_id
    async with db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await conn.execute("set local statement_timeout = '15s'")
            await conn.execute("set local lock_timeout = '5s'")
            await conn.execute(
                "insert into demo_accounts (user_id, note) values ($1, 'test')",
                user_id,
            )
            yield conn, user_id
        finally:
            await tr.rollback()


async def _sqlstate_as_demo(conn, user_id: UUID, statement: str, *args) -> str | None:
    """Run `statement` under a simulated demo JWT; return its SQLSTATE or None.

    Each call gets its own savepoint because a failed statement poisons the
    surrounding transaction, and these tests deliberately expect failures.
    """
    inner = conn.transaction()
    await inner.start()
    try:
        await conn.execute("set local role authenticated")
        await conn.execute(
            "select set_config('request.jwt.claims', $1, true)",
            json.dumps({"sub": str(user_id), "role": "authenticated"}),
        )
        await conn.execute(statement, *args)
        return None
    except asyncpg.PostgresError as exc:
        return exc.sqlstate
    finally:
        await inner.rollback()


# ── Coverage: the properties that must hold for the whole schema ─────────────


async def test_every_public_table_carries_the_write_guard(db_pool) -> None:
    missing = await db_pool.fetch(
        """
        select c.relname
          from pg_class c
          join pg_namespace n on n.oid = c.relnamespace
         where n.nspname = 'public'
           and c.relkind in ('r', 'p')
           and not exists (select 1 from pg_trigger t
                            where t.tgrelid = c.oid
                              and t.tgname = 'demo_write_guard'
                              and not t.tgisinternal)
         order by c.relname
        """
    )
    assert [r["relname"] for r in missing] == [], (
        "Tables without the demo write guard are writable by the shared public "
        "demo account. Re-run the attachment loop in "
        "supabase/migrations/20260901000000_demo_mode_foundation.sql."
    )


async def test_every_public_table_carries_the_truncate_guard(db_pool) -> None:
    missing = await db_pool.fetch(
        """
        select c.relname
          from pg_class c
          join pg_namespace n on n.oid = c.relnamespace
         where n.nspname = 'public'
           and c.relkind in ('r', 'p')
           and not exists (select 1 from pg_trigger t
                            where t.tgrelid = c.oid
                              and t.tgname = 'demo_truncate_guard'
                              and not t.tgisinternal)
         order by c.relname
        """
    )
    assert [r["relname"] for r in missing] == []


async def test_no_public_view_is_writable_by_authenticated(db_pool) -> None:
    """A writable view is the one shape that could route around the guard.

    Statement triggers fire on a view only when it has an INSTEAD OF trigger, so
    rather than attach triggers to views we assert the property that makes them
    irrelevant. Supabase's bootstrap `grant all` is what puts these grants there
    in the first place, so this regresses on any new view.
    """
    writable = await db_pool.fetch(
        """
        select c.relname
          from pg_class c
          join pg_namespace n on n.oid = c.relnamespace
         where n.nspname = 'public' and c.relkind = 'v'
           and (has_table_privilege('authenticated', c.oid, 'INSERT')
             or has_table_privilege('authenticated', c.oid, 'UPDATE')
             or has_table_privilege('authenticated', c.oid, 'DELETE'))
         order by c.relname
        """
    )
    assert [r["relname"] for r in writable] == []


async def test_membership_guard_is_attached(db_pool) -> None:
    assert await db_pool.fetchval(
        """
        select exists (select 1 from pg_trigger t
                         join pg_class c on c.oid = t.tgrelid
                        where c.relname = 'hunt_members'
                          and t.tgname = 'demo_membership_guard'
                          and not t.tgisinternal)
        """
    )


# ── DM-1: cleaned_text is service-role only, for everyone ────────────────────


async def test_cleaned_text_is_not_readable_by_authenticated(db_pool) -> None:
    """DESIGN §16 has claimed this since 2026-06-28; DM-1 made it true."""
    assert not await db_pool.fetchval(
        "select has_column_privilege('authenticated', 'public.property_sources',"
        " 'cleaned_text', 'SELECT')"
    )


async def test_other_property_source_columns_stay_readable(db_pool) -> None:
    """The revoke drops a table-level grant; this catches over-revoking.

    A new column added later will show up here, which is intended: it is
    invisible to members until someone re-grants it, and a failing test is how
    they find that out.
    """
    hidden = await db_pool.fetch(
        """
        select column_name
          from information_schema.columns
         where table_schema = 'public' and table_name = 'property_sources'
           and column_name <> 'cleaned_text'
           and not has_column_privilege('authenticated',
                                        'public.property_sources',
                                        column_name, 'SELECT')
         order by ordinal_position
        """
    )
    assert [r["column_name"] for r in hidden] == []


# ── DM-3: writes carrying a demo JWT are refused ─────────────────────────────


@pytest.mark.parametrize(
    "statement",
    [
        "insert into comments (hunt_listing_id, user_id, body)"
        " values (gen_random_uuid(), gen_random_uuid(), 'x')",
        "insert into jobs (hunt_id, type, state)"
        " values (gen_random_uuid(), 'ingest', 'queued')",
        "insert into hunt_listings (hunt_id, property_id, added_by)"
        " values (gen_random_uuid(), gen_random_uuid(), gen_random_uuid())",
        "update properties set name = 'pwned'",
        "delete from comments",
        "delete from visit_entries",
        "update site_settings set demo_enabled = true",
        "delete from demo_accounts",
    ],
)
async def test_demo_writes_are_refused(demo_conn, statement: str) -> None:
    conn, user_id = demo_conn
    assert await _sqlstate_as_demo(conn, user_id, statement) == "42501"


async def test_a_non_demo_member_can_still_write(db_pool, seeded_users) -> None:
    """The inverse of the guard: it must not fire for anybody real."""
    user_id = seeded_users["owner"].user_id
    async with db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            state = await _sqlstate_as_demo(
                conn, user_id, "update properties set name = name"
            )
            assert state != "42501"
        finally:
            await tr.rollback()


# ── DM-1: reads are scoped, and the kill switch reaches PostgREST ────────────


async def _visible_property_ids(conn, user_id: UUID) -> set:
    inner = conn.transaction()
    await inner.start()
    try:
        await conn.execute("set local role authenticated")
        await conn.execute(
            "select set_config('request.jwt.claims', $1, true)",
            json.dumps({"sub": str(user_id), "role": "authenticated"}),
        )
        return {r["id"] for r in await conn.fetch("select id from properties")}
    finally:
        await inner.rollback()


async def test_demo_reads_are_scoped_to_the_demo_hunt(collab_hunt, demo_conn) -> None:
    """Not merely "returns nothing" -- exactly the Demo Hunt's own rows.

    Compared against ground truth computed from hunt_listings rather than a
    hardcoded count, so this keeps testing scoping rather than arithmetic if the
    fixture's seed ever changes.
    """
    conn, user_id = demo_conn
    hunt_id = UUID(collab_hunt["hunt_id"])
    await conn.execute(
        "update site_settings set demo_enabled = true, demo_hunt_id = $1", hunt_id
    )

    expected = {
        r["property_id"]
        for r in await conn.fetch(
            "select distinct property_id from hunt_listings where hunt_id = $1",
            hunt_id,
        )
    }
    assert expected, "fixture should have put properties in the hunt"

    total = await conn.fetchval("select count(*) from properties")
    assert total > len(expected), "there must be out-of-scope rows to exclude"

    assert await _visible_property_ids(conn, user_id) == expected


async def test_kill_switch_darkens_reads_at_the_database(collab_hunt, demo_conn) -> None:
    """demo_enabled lives in RLS, so disabling it reaches PostgREST and Realtime.

    Checked only in FastAPI it would gate FastAPI, and a visitor holding a token
    would keep reading straight through PostgREST.
    """
    conn, user_id = demo_conn
    hunt_id = UUID(collab_hunt["hunt_id"])

    await conn.execute(
        "update site_settings set demo_enabled = true, demo_hunt_id = $1", hunt_id
    )
    assert await _visible_property_ids(conn, user_id)

    await conn.execute("update site_settings set demo_enabled = false")
    assert await _visible_property_ids(conn, user_id) == set()


# ── DM-4: the subject guard, where auth.uid() cannot help ────────────────────


async def test_demo_account_cannot_join_a_foreign_hunt(
    collab_hunt, demo_conn, seeded_users
) -> None:
    """Runs service-role, with no JWT claims -- the invite path's exact context.

    `accept_hunt_invite` and `join_hunt_invitation_link` execute this way, so
    auth.uid() is null and the session-keyed guard is blind by design.
    """
    conn, user_id = demo_conn
    assert await conn.fetchval("select auth.uid()") is None

    other_hunt = await conn.fetchval(
        "insert into hunts (name, owner_id) values ('Real Hunt', $1) returning id",
        seeded_users["owner"].user_id,
    )
    await conn.execute(
        "update site_settings set demo_hunt_id = $1", UUID(collab_hunt["hunt_id"])
    )

    inner = conn.transaction()
    await inner.start()
    try:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute(
                "insert into hunt_members (hunt_id, user_id, role)"
                " values ($1, $2, 'member')",
                other_hunt,
                user_id,
            )
    finally:
        await inner.rollback()


async def test_demo_account_cannot_own_a_hunt(collab_hunt, demo_conn) -> None:
    conn, user_id = demo_conn
    await conn.execute(
        "update site_settings set demo_hunt_id = $1", UUID(collab_hunt["hunt_id"])
    )
    inner = conn.transaction()
    await inner.start()
    try:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute(
                "insert into hunt_members (hunt_id, user_id, role)"
                " values ($1, $2, 'owner')",
                UUID(collab_hunt["hunt_id"]),
                user_id,
            )
    finally:
        await inner.rollback()


async def test_demo_account_may_curate_the_demo_hunt(collab_hunt, demo_conn) -> None:
    """The seed path must work, or the feature cannot be set up at all."""
    conn, user_id = demo_conn
    hunt_id = UUID(collab_hunt["hunt_id"])
    await conn.execute("update site_settings set demo_hunt_id = $1", hunt_id)
    await conn.execute(
        "delete from hunt_members where hunt_id = $1 and user_id = $2",
        hunt_id,
        user_id,
    )
    await conn.execute(
        "insert into hunt_members (hunt_id, user_id, role) values ($1, $2, 'curator')",
        hunt_id,
        user_id,
    )
    assert (
        await conn.fetchval(
            "select role::text from hunt_members where hunt_id = $1 and user_id = $2",
            hunt_id,
            user_id,
        )
        == "curator"
    )


async def test_ordinary_membership_is_unaffected(db_pool, collab_hunt, seeded_users) -> None:
    conn_user = seeded_users["outsider"].user_id
    async with db_pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await conn.execute(
                "insert into hunt_members (hunt_id, user_id, role)"
                " values ($1, $2, 'member')",
                UUID(collab_hunt["hunt_id"]),
                conn_user,
            )
        finally:
            await tr.rollback()
