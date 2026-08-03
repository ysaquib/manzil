"""PR-1 account-creation boundary against the local GoTrue instance."""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
from manzil_api.config import get_settings
from manzil_api.database import create_service_client

pytestmark = pytest.mark.asyncio


async def test_anonymous_signup_is_disabled(db_pool) -> None:  # type: ignore[no-untyped-def]
    settings = get_settings()
    email = f"public-signup-{uuid4().hex}@test.manzil"
    headers = {
        "apikey": settings.supabase_anon_key,
        "Authorization": f"Bearer {settings.supabase_anon_key}",
    }

    try:
        async with httpx.AsyncClient(base_url=settings.supabase_url, headers=headers) as client:
            response = await client.post(
                "/auth/v1/signup",
                json={"email": email, "password": "must-not-create-an-account"},
            )

        assert response.status_code in {400, 403, 422}
        assert await db_pool.fetchval(
            "select count(*) from auth.users where lower(email) = lower($1)", email
        ) == 0
    finally:
        # If a developer runs this against stale, signup-enabled containers,
        # fail loudly without leaving the probe account behind.
        created_id = await db_pool.fetchval(
            "select id from auth.users where lower(email) = lower($1)", email
        )
        if created_id is not None:
            create_service_client(settings).auth.admin.delete_user(str(created_id))


async def test_unknown_email_otp_cannot_create_an_account(db_pool) -> None:  # type: ignore[no-untyped-def]
    settings = get_settings()
    email = f"public-otp-{uuid4().hex}@test.manzil"
    headers = {
        "apikey": settings.supabase_anon_key,
        "Authorization": f"Bearer {settings.supabase_anon_key}",
    }

    async with httpx.AsyncClient(base_url=settings.supabase_url, headers=headers) as client:
        # GoTrue deliberately returns a non-enumerating response; the database
        # assertion is the security claim that matters.
        await client.post("/auth/v1/otp", json={"email": email, "create_user": False})

    assert await db_pool.fetchval(
        "select count(*) from auth.users where lower(email) = lower($1)", email
    ) == 0
