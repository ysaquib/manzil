"""Schema-assertion test for migration 0002 (P1-1): the per-hunt + pipeline
tables, remaining enums, and the key constraints/indexes exist after a
`supabase db reset`.

Environment-dependent: needs the local Supabase Postgres. Skips cleanly when
the DB is unreachable (CI has no Postgres — it must stay green), mirroring how
the API tests default DATABASE_URL to the local stack. No live LLM calls, no
data writes — pure catalog introspection.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import asyncpg
import pytest
import pytest_asyncio

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
)

# Per-hunt + pipeline tables 0002 must create (DESIGN §8.2).
EXPECTED_TABLES = {
    "hunts",
    "hunt_members",
    "invites",
    "hunt_listings",
    "rubric_criteria",
    "overrides",
    "fee_checklist",
    "scores",
    "comments",
    "ratings",
    "jobs",
    "job_events",
}

# Enum types 0002 adds (DESIGN §8.1) -> their exact value sets.
EXPECTED_ENUMS = {
    "hunt_role": {"owner", "curator", "member"},
    "job_type": {"ingest", "refresh", "rescore", "investigate"},
    "job_state": {"queued", "running", "waiting_user", "done", "failed", "cancelled"},
    "value_state": {"extracted", "manual", "estimated", "unknown"},
}

# Indexes the P1-1 row names (claim/heartbeat, job_events, hunt-scoped extraction,
# latest override).
EXPECTED_INDEXES = {
    "jobs_claim_idx",
    "jobs_heartbeat_idx",
    "job_events_job_id_idx",
    "extractions_hunt_criterion_idx",
    "overrides_latest_idx",
}


@pytest_asyncio.fixture
async def conn() -> AsyncIterator[asyncpg.Connection]:
    try:
        connection = await asyncpg.connect(DATABASE_URL, timeout=5)
    except (OSError, asyncpg.PostgresError) as exc:  # pragma: no cover - env guard
        pytest.skip(f"Postgres unreachable at {DATABASE_URL}: {exc}")
    try:
        yield connection
    finally:
        await connection.close()


async def test_tables_exist(conn: asyncpg.Connection) -> None:
    rows = await conn.fetch("select tablename from pg_tables where schemaname = 'public'")
    present = {r["tablename"] for r in rows}
    assert present >= EXPECTED_TABLES, f"missing tables: {EXPECTED_TABLES - present}"


async def test_enums_and_values(conn: asyncpg.Connection) -> None:
    for enum_name, values in EXPECTED_ENUMS.items():
        rows = await conn.fetch(
            """
            select e.enumlabel
            from pg_type t
            join pg_enum e on e.enumtypid = t.oid
            where t.typname = $1
            """,
            enum_name,
        )
        present = {r["enumlabel"] for r in rows}
        assert present == values, f"{enum_name}: expected {values}, got {present}"


async def test_indexes_exist(conn: asyncpg.Connection) -> None:
    rows = await conn.fetch("select indexname from pg_indexes where schemaname = 'public'")
    present = {r["indexname"] for r in rows}
    assert present >= EXPECTED_INDEXES, f"missing indexes: {EXPECTED_INDEXES - present}"


async def test_key_unique_constraints(conn: asyncpg.Connection) -> None:
    # scores PK on (hunt_listing_id, floor_plan_id); fee_checklist PK on
    # (hunt_listing_id, fee_slot). Assert the pinned column tuple is a unique key.
    for table, cols in (
        ("scores", ["hunt_listing_id", "floor_plan_id"]),
        ("fee_checklist", ["hunt_listing_id", "fee_slot"]),
        ("hunt_listings", ["hunt_id", "property_id"]),
    ):
        rows = await conn.fetch(
            """
            select array_agg(a.attname order by array_position(c.conkey, a.attnum))
                       as cols
            from pg_constraint c
            join pg_class rel on rel.oid = c.conrelid
            join pg_attribute a on a.attrelid = rel.oid and a.attnum = any (c.conkey)
            where rel.relname = $1
              and c.contype in ('p', 'u')
            group by c.oid
            """,
            table,
        )
        col_sets = [set(r["cols"]) for r in rows]
        assert set(cols) in col_sets, f"{table}: no unique key on {cols}; found {col_sets}"


async def test_extractions_hunt_id_fk(conn: asyncpg.Connection) -> None:
    # The FK deferred from 0001 now points extractions.hunt_id -> hunts.id.
    row = await conn.fetchrow(
        """
        select confrelid::regclass::text as ref
        from pg_constraint
        where conname = 'extractions_hunt_id_fkey' and contype = 'f'
        """
    )
    assert row is not None, "extractions_hunt_id_fkey missing"
    assert row["ref"] == "hunts"
