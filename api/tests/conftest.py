"""Shared API test fixtures (Phase 1 plan §4.1, §8).

An `httpx.AsyncClient` over `ASGITransport` with `dependency_overrides` faking
auth — no running server, no lifespan (so no DB pool needed for routing tests).
Dummy env is set before the app imports so `Settings` constructs in CI without
real secrets; tests that touch the DB run against the local Supabase stack.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from dotenv import load_dotenv
from local_supabase import LOCAL_ANON_KEY, LOCAL_SERVICE_ROLE_KEY, LOCAL_SUPABASE_URL

load_dotenv(Path(__file__).resolve().parents[2] / "infra" / ".env", override=False)
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)

if not os.environ.get("SUPABASE_URL", "").strip():
    os.environ["SUPABASE_URL"] = LOCAL_SUPABASE_URL
if not os.environ.get("SUPABASE_ANON_KEY", "").strip():
    os.environ["SUPABASE_ANON_KEY"] = LOCAL_ANON_KEY
if not os.environ.get("SUPABASE_SECRET_KEY", "").strip():
    # The local CLI currently exposes only the legacy service-role JWT. The
    # production variable deliberately has the new API-key name.
    os.environ["SUPABASE_SECRET_KEY"] = LOCAL_SERVICE_ROLE_KEY
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres")
os.environ.setdefault("API_ENVIRONMENT", "local")
os.environ.setdefault("MANZIL_WORKER_INPROCESS", "false")

import asyncpg  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from api_helpers import FAKE_USER  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from manzil_api.config import get_settings  # noqa: E402
from manzil_api.database import (  # noqa: E402
    create_anon_client,
    create_service_client,
    create_user_client,
)
from manzil_api.main import create_app  # noqa: E402

DATABASE_URL = os.environ["DATABASE_URL"]


@dataclass(frozen=True)
class TestIdentity:
    user_id: str
    email: str
    token: str

    @property
    def supabase(self):  # type: ignore[no-untyped-def]
        return create_user_client(get_settings(), self.token)



async def _purge_user_references(pool, user_id: str) -> None:
    """Delete everything that would block removing this account.

    Eleven columns reference `auth.users` with NO ACTION, so a seeded user who
    created a Visit cannot be deleted — and because `seeded_users` suppresses
    the failure and then tries to *create* the same email, an interrupted run
    used to break the entire suite with "a user with this email address has
    already been registered".

    Reflected from the catalog so a future NO ACTION reference is covered
    without anyone remembering to add it here. Identifiers come from
    `pg_constraint`, never from a caller.
    """
    fks = await pool.fetch(
        """
        select c.conrelid::regclass::text as tbl, a.attname as col
        from pg_constraint c
        join pg_attribute a on a.attrelid = c.conrelid and a.attnum = c.conkey[1]
        where c.contype = 'f'
          and c.confrelid = 'auth.users'::regclass
          and c.connamespace = 'public'::regnamespace
          and c.confdeltype = 'a'
        """
    )
    for fk in fks:
        with suppress(Exception):
            await pool.execute(f'delete from {fk["tbl"]} where {fk["col"]} = $1', UUID(user_id))


@pytest.fixture(scope="session")
def seeded_users() -> dict[str, TestIdentity]:
    admin = create_service_client(get_settings())
    specs = {
        "owner": (FAKE_USER.id, "owner@test.manzil"),
        "curator": ("00000000-0000-0000-0000-000000000002", "curator@test.manzil"),
        "member": ("00000000-0000-0000-0000-000000000003", "member@test.manzil"),
        "outsider": ("00000000-0000-0000-0000-000000000004", "outsider@test.manzil"),
    }
    password = "manzil-local-test-password"
    identities: dict[str, TestIdentity] = {}

    async def _purge_all() -> None:
        pool = await asyncpg.create_pool(DATABASE_URL, timeout=5, min_size=1, max_size=2)
        try:
            for uid, _ in specs.values():
                await _purge_user_references(pool, uid)
        finally:
            await pool.close()

    # Clear anything a previous (possibly interrupted) run left pointing at
    # these accounts, so the delete below actually succeeds.
    with suppress(Exception):
        asyncio.run(_purge_all())

    for user_id, email in specs.values():
        with suppress(Exception):
            admin.auth.admin.delete_user(user_id)
        admin.auth.admin.create_user(
            {"id": user_id, "email": email, "password": password, "email_confirm": True}
        )
        auth_client = create_anon_client(get_settings())
        session = auth_client.auth.sign_in_with_password({"email": email, "password": password})
        identities[email.split("@")[0]] = TestIdentity(
            user_id=user_id, email=email, token=session.session.access_token
        )
    yield identities
    for user_id, _ in specs.values():
        with suppress(Exception):
            admin.auth.admin.delete_user(user_id)


@pytest.fixture
def app():
    return create_app()


async def _http_client(app, identity: TestIdentity) -> AsyncIterator[AsyncClient]:  # type: ignore[no-untyped-def]
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {identity.token}"},
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def as_owner(app, seeded_users) -> AsyncIterator[AsyncClient]:  # type: ignore[no-untyped-def]
    async for ac in _http_client(app, seeded_users["owner"]):
        yield ac


@pytest_asyncio.fixture
async def as_curator(app, seeded_users) -> AsyncIterator[AsyncClient]:  # type: ignore[no-untyped-def]
    async for ac in _http_client(app, seeded_users["curator"]):
        yield ac


@pytest_asyncio.fixture
async def as_member(app, seeded_users) -> AsyncIterator[AsyncClient]:  # type: ignore[no-untyped-def]
    async for ac in _http_client(app, seeded_users["member"]):
        yield ac


@pytest_asyncio.fixture
async def as_outsider(app, seeded_users) -> AsyncIterator[AsyncClient]:  # type: ignore[no-untyped-def]
    async for ac in _http_client(app, seeded_users["outsider"]):
        yield ac


@pytest_asyncio.fixture
async def client(as_owner: AsyncClient) -> AsyncIterator[AsyncClient]:
    yield as_owner


@pytest_asyncio.fixture
async def db_pool():
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, timeout=5, min_size=1, max_size=4)
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"Postgres unreachable at {DATABASE_URL}: {exc}")
    yield pool
    await pool.close()


@pytest_asyncio.fixture
async def collab_hunt(db_pool, seeded_users):  # type: ignore[no-untyped-def]
    """Canonical Owner/Curator/Member Hunt for P2 permission tests."""
    owner = seeded_users["owner"]
    curator = seeded_users["curator"]
    member = seeded_users["member"]
    hunt_id = await db_pool.fetchval(
        "insert into hunts (name, owner_id) values ('Collab Hunt', $1) returning id",
        owner.user_id,
    )
    await db_pool.executemany(
        "insert into hunt_members (hunt_id, user_id, role) values ($1, $2, $3)",
        [
            (hunt_id, curator.user_id, "curator"),
            (hunt_id, member.user_id, "member"),
        ],
    )
    property_ids = await db_pool.fetch(
        """
        insert into properties (name, canonical_address)
        values ('Member Property', '1 Test St'), ('Owner Property', '2 Test St')
        returning id
        """
    )
    member_listing = await db_pool.fetchval(
        """insert into hunt_listings (hunt_id, property_id, added_by)
           values ($1, $2, $3) returning id""",
        hunt_id,
        property_ids[0]["id"],
        member.user_id,
    )
    owner_listing = await db_pool.fetchval(
        """insert into hunt_listings (hunt_id, property_id, added_by)
           values ($1, $2, $3) returning id""",
        hunt_id,
        property_ids[1]["id"],
        owner.user_id,
    )
    source_ids = await db_pool.fetch(
        """
        insert into property_sources (property_id, url, site_domain)
        values ($1::uuid, 'https://member.example/listing/' || $1::uuid::text, 'member.example'),
               ($2::uuid, 'https://owner.example/listing/' || $2::uuid::text, 'owner.example')
        returning id
        """,
        property_ids[0]["id"],
        property_ids[1]["id"],
    )
    await db_pool.executemany(
        """
        insert into floor_plans (property_id, source_id, plan_name, beds, baths)
        values ($1, $2, $3, $4, $5)
        """,
        [
            (property_ids[0]["id"], source_ids[0]["id"], "Member Two Bed", 2, 1),
            (property_ids[1]["id"], source_ids[1]["id"], "Owner Two Bed", 2, 1),
            (property_ids[1]["id"], source_ids[1]["id"], "Owner One Bed", 1, 1),
        ],
    )
    # Property and Floor Plan ids are exposed too: Visits (VC-1) hang off a
    # Property rather than a Listing, and their same-Property guard needs a
    # Floor Plan from each side to prove it denies the foreign one.
    #
    # `order by plan_name` matters: the Owner Property carries both a 2-bed and a
    # 1-bed plan, so an unordered pick made `owner_plan_id` — and therefore the
    # Unit Group key a visit derives from it — vary between runs. "Owner One Bed"
    # sorts first, so `owner_plan_id` is deterministically the **1 bd / 1 ba**
    # plan and its Unit Group key is "1-1".
    plans = await db_pool.fetch(
        """
        select id, property_id, beds, baths, plan_name
        from floor_plans
        where property_id = any($1::uuid[])
        order by property_id, plan_name
        """,
        [property_ids[0]["id"], property_ids[1]["id"]],
    )
    yield {
        "hunt_id": str(hunt_id),
        "member_listing_id": str(member_listing),
        "owner_listing_id": str(owner_listing),
        "member_property_id": str(property_ids[0]["id"]),
        "owner_property_id": str(property_ids[1]["id"]),
        # "Member Two Bed" — 2 bd / 1 ba, Unit Group key "2-1".
        "member_plan_id": str(
            next(p["id"] for p in plans if p["property_id"] == property_ids[0]["id"])
        ),
        # "Owner One Bed" — 1 bd / 1 ba, Unit Group key "1-1".
        "owner_plan_id": str(
            next(p["id"] for p in plans if p["property_id"] == property_ids[1]["id"])
        ),
    }
    await db_pool.execute("delete from hunts where id = $1", hunt_id)


@pytest_asyncio.fixture
async def no_primordial_admin(db_pool):  # type: ignore[no-untyped-def]
    """Yield a database with no primordial admin, and put back whatever was
    there afterwards.

    A real deployment — and any dev database somebody has bootstrapped — already
    has one, and `site_admins_one_primordial_idx` allows exactly one. Without
    this the tests below pass only on a virgin database, which is precisely the
    database nobody has.
    """
    existing = await db_pool.fetchrow(
        "select user_id, granted_by, note from site_admins where is_primordial"
    )
    if existing is not None:
        await db_pool.execute(
            "alter table site_admins disable trigger site_admins_protect_primordial"
        )
        await db_pool.execute(
            "delete from site_admins where user_id = $1", existing["user_id"]
        )
        await db_pool.execute(
            "alter table site_admins enable trigger site_admins_protect_primordial"
        )
    try:
        yield
    finally:
        if existing is not None:
            await db_pool.execute(
                "insert into site_admins (user_id, granted_by, note, is_primordial) "
                "values ($1, $2, $3, true) on conflict (user_id) do update "
                "set is_primordial = true",
                existing["user_id"],
                existing["granted_by"],
                existing["note"],
            )
