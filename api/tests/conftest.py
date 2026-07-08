"""Shared API test fixtures (Phase 1 plan §4.1, §8).

An `httpx.AsyncClient` over `ASGITransport` with `dependency_overrides` faking
auth — no running server, no lifespan (so no DB pool needed for routing tests).
Dummy env is set before the app imports so `Settings` constructs in CI without
real secrets; tests that touch the DB run against the local Supabase stack.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

# Set before importing the app so `Settings()` constructs (real values come from
# the local Supabase stack for DB-touching tests).
os.environ.setdefault("SUPABASE_URL", "http://127.0.0.1:54321")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-key")
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres")
os.environ.setdefault("API_ENVIRONMENT", "local")
os.environ.setdefault("MANZIL_WORKER_INPROCESS", "false")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from manzil_api.dependencies import UserContext, get_current_user
from manzil_api.main import create_app

FAKE_USER = UserContext(
    id="00000000-0000-0000-0000-000000000001",
    email="dev@example.com",
    access_token="fake-token",
)


@pytest.fixture
def app():
    application = create_app()
    application.dependency_overrides[get_current_user] = lambda: FAKE_USER
    return application


@pytest_asyncio.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
