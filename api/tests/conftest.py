"""Shared API test fixtures (Phase 1 plan §4.1, §8).

An `httpx.AsyncClient` over `ASGITransport` with `dependency_overrides` faking
auth — no running server, no lifespan (so no DB pool needed for routing tests).
Dummy env is set before the app imports so `Settings` constructs in CI without
real secrets; tests that touch the DB run against the local Supabase stack.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
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
from httpx import ASGITransport, AsyncClient  # noqa: E402
from manzil_api.config import get_settings  # noqa: E402
from manzil_api.database import create_anon_client  # noqa: E402
from manzil_api.dependencies import UserContext, get_current_user, get_user_client  # noqa: E402
from manzil_api.main import create_app  # noqa: E402

DATABASE_URL = os.environ["DATABASE_URL"]

FAKE_USER = UserContext(
    id="00000000-0000-0000-0000-000000000001",
    email="dev@example.com",
    access_token="fake-token",
)


def _anon_client():
    return create_anon_client(get_settings())


@pytest.fixture
def app():
    application = create_app()
    application.dependency_overrides[get_current_user] = lambda: FAKE_USER
    application.dependency_overrides[get_user_client] = _anon_client
    return application


@pytest_asyncio.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def db_pool():
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, timeout=5, min_size=1, max_size=4)
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"Postgres unreachable at {DATABASE_URL}: {exc}")
    yield pool
    await pool.close()
