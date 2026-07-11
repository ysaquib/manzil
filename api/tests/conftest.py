"""Shared API test fixtures (Phase 1 plan §4.1, §8).

An `httpx.AsyncClient` over `ASGITransport` with `dependency_overrides` faking
auth — no running server, no lifespan (so no DB pool needed for routing tests).
Dummy env is set before the app imports so `Settings` constructs in CI without
real secrets; tests that touch the DB run against the local Supabase stack.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / "infra" / ".env", override=False)
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)

# Supabase CLI local stack defaults (public demo JWTs — not production secrets).
_LOCAL_SUPABASE_URL = "http://127.0.0.1:54321"
_LOCAL_ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6ImFub24iLCJleHAiOjE5ODM4MTI5OTZ9."
    "CRXP1A7WOeoJeXxjNni43kdQwgnWNReilDMblYTn_I0"
)

if not os.environ.get("SUPABASE_URL", "").strip():
    os.environ["SUPABASE_URL"] = _LOCAL_SUPABASE_URL
_LOCAL_SERVICE_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImV4cCI6OjE5ODM4MTI5OTZ9."
    "EGIM96RAZx35lJzdJsyH-qQwv8Hdp7fsn3W0YpN81IU"
)
if not os.environ.get("SUPABASE_ANON_KEY", "").strip():
    os.environ["SUPABASE_ANON_KEY"] = _LOCAL_ANON_KEY
if not os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip():
    os.environ["SUPABASE_SERVICE_ROLE_KEY"] = _LOCAL_SERVICE_KEY
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
    yield {
        "hunt_id": str(hunt_id),
        "member_listing_id": str(member_listing),
        "owner_listing_id": str(owner_listing),
    }
    await db_pool.execute("delete from hunts where id = $1", hunt_id)
