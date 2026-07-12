from __future__ import annotations

from httpx import AsyncClient


async def test_profile_onboarding_upserts_and_trims(
    as_owner: AsyncClient, seeded_users
) -> None:
    missing = await as_owner.get("/v1/profile")
    assert missing.status_code == 200
    assert missing.json() is None

    created = await as_owner.put(
        "/v1/profile", json={"default_display_name": "  Yusuf  "}
    )
    assert created.status_code == 200
    assert created.json()["default_display_name"] == "Yusuf"
    assert created.json()["user_id"] == seeded_users["owner"].user_id

    fetched = await as_owner.get("/v1/profile")
    assert fetched.json()["default_display_name"] == "Yusuf"


async def test_profile_rejects_blank_name(as_owner: AsyncClient) -> None:
    response = await as_owner.put("/v1/profile", json={"default_display_name": "   "})
    assert response.status_code == 422
