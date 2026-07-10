"""Misconfiguration and error-envelope tests."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from manzil_api.config import Settings, get_settings
from manzil_api.database import create_anon_client
from manzil_api.dependencies import UserContext, get_current_user, get_user_client
from manzil_api.exceptions import BackendMisconfigured
from manzil_api.main import create_app


@pytest.mark.asyncio
async def test_missing_supabase_key_returns_enveloped_503_with_cors() -> None:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: UserContext(
        id="00000000-0000-0000-0000-000000000001",
        email=None,
        access_token="t",
    )

    def _bad_client() -> None:
        raise BackendMisconfigured("SUPABASE_ANON_KEY is not configured")

    app.dependency_overrides[get_user_client] = _bad_client

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/v1/hunts/00000000-0000-0000-0000-000000000001/jobs",
            headers={"Origin": "http://localhost:5173", "Authorization": "Bearer t"},
        )
    assert resp.status_code == 503
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"
    body = resp.json()
    assert body["code"] == "backend_misconfigured"


def test_create_anon_client_rejects_empty_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    settings = Settings(
        supabase_url="http://127.0.0.1:54321",
        supabase_anon_key="",
        supabase_service_role_key="x",
        database_url="postgresql://postgres:postgres@127.0.0.1:54322/postgres",
    )
    with pytest.raises(BackendMisconfigured, match="SUPABASE_ANON_KEY"):
        create_anon_client(settings)
    get_settings.cache_clear()
