from __future__ import annotations

from contextlib import suppress
from uuid import UUID

import pytest
from httpx import AsyncClient
from manzil_api.config import get_settings
from manzil_api.database import create_service_client

DEFAULT_MEMBER_COLOR_TOKENS = ("moss", "ochre", "brick", "olive", "stone", "plum")


async def test_profile_onboarding_upserts_and_trims(
    as_owner: AsyncClient, seeded_users, db_pool
) -> None:
    await db_pool.execute(
        "delete from user_profiles where user_id = $1",
        UUID(seeded_users["owner"].user_id),
    )
    missing = await as_owner.get("/v1/profile")
    assert missing.status_code == 200
    assert missing.json() is None

    created = await as_owner.put("/v1/profile", json={"default_display_name": "  Yusuf  "})
    assert created.status_code == 200
    assert created.json()["default_display_name"] == "Yusuf"
    assert created.json()["user_id"] == seeded_users["owner"].user_id
    assert created.json()["default_color"] in DEFAULT_MEMBER_COLOR_TOKENS

    fetched = await as_owner.get("/v1/profile")
    assert fetched.json()["default_display_name"] == "Yusuf"
    assert fetched.json()["default_color"] == created.json()["default_color"]


async def test_profile_rejects_blank_name(as_owner: AsyncClient) -> None:
    response = await as_owner.put("/v1/profile", json={"default_display_name": "   "})
    assert response.status_code == 422


async def test_profile_rejects_obsolete_and_null_colors(as_owner: AsyncClient) -> None:
    for bad in ("dark", "gray", "dusk", "clay", None):
        response = await as_owner.put(
            "/v1/profile",
            json={"default_display_name": "Yusuf", "default_color": bad},
        )
        assert response.status_code == 422, bad


async def test_profile_accepts_custom_hex(as_owner: AsyncClient, db_pool, seeded_users) -> None:
    await db_pool.execute(
        "delete from user_profiles where user_id = $1",
        UUID(seeded_users["owner"].user_id),
    )
    response = await as_owner.put(
        "/v1/profile",
        json={"default_display_name": "Yusuf", "default_color": "#aabbcc"},
    )
    assert response.status_code == 200
    assert response.json()["default_color"] == "#AABBCC"


async def test_profile_accepts_new_theme_palette_color(as_owner: AsyncClient) -> None:
    response = await as_owner.put(
        "/v1/profile",
        json={"default_display_name": "Yusuf", "default_color": "cyan"},
    )
    assert response.status_code == 200
    assert response.json()["default_color"] == "cyan"


@pytest.mark.asyncio
async def test_profile_default_color_assigns_unused_then_wraps(
    as_owner: AsyncClient,
    as_curator: AsyncClient,
    as_member: AsyncClient,
    as_outsider: AsyncClient,
    db_pool,
    seeded_users,
) -> None:
    # The colour trigger assigns the first *globally* unused token, so this test
    # genuinely needs an empty table — scoping the delete to the seeded four
    # would leave other profiles holding tokens and the wrap would never happen.
    # So it snapshots and restores rather than wiping: a bare
    # `delete from user_profiles` also took the developer's own profile, which
    # silently bounces them to /onboarding on their next page load.
    saved = await db_pool.fetch(
        "select user_id, default_display_name, default_color, created_at, updated_at "
        "from user_profiles"
    )
    await db_pool.execute("delete from user_profiles")

    clients = [
        (as_owner, "Owner"),
        (as_curator, "Curator"),
        (as_member, "Member"),
        (as_outsider, "Outsider"),
    ]
    assigned: list[str] = []
    for client, name in clients:
        resp = await client.put("/v1/profile", json={"default_display_name": name})
        assert resp.status_code == 200
        assigned.append(resp.json()["default_color"])

    assert assigned == list(DEFAULT_MEMBER_COLOR_TOKENS[:4])
    assert len(set(assigned)) == 4

    admin = create_service_client(get_settings())
    extra_ids: list[str] = []
    try:
        for i in range(4):
            email = f"palette-extra-{i}@test.manzil"
            created = admin.auth.admin.create_user(
                {
                    "email": email,
                    "password": "manzil-local-test-password",
                    "email_confirm": True,
                }
            )
            user_id = created.user.id
            extra_ids.append(user_id)
            color = await db_pool.fetchval(
                """
                insert into user_profiles (user_id, default_display_name)
                values ($1, $2)
                returning default_color
                """,
                UUID(user_id),
                f"Extra {i}",
            )
            assigned.append(color)

        assert assigned[:6] == list(DEFAULT_MEMBER_COLOR_TOKENS)
        assert assigned[6] == "moss"
        assert assigned[7] == "ochre"
    finally:
        for user_id in extra_ids:
            with suppress(Exception):
                admin.auth.admin.delete_user(user_id)
        await db_pool.execute(
            "delete from user_profiles where user_id = any($1::uuid[])",
            [UUID(uid) for uid in extra_ids],
        )
        # Leave the database as it was found.
        for row in saved:
            await db_pool.execute(
                "insert into user_profiles "
                "(user_id, default_display_name, default_color, created_at, updated_at) "
                "values ($1, $2, $3, $4, $5) on conflict (user_id) do update set "
                "default_display_name = excluded.default_display_name, "
                "default_color = excluded.default_color",
                row["user_id"],
                row["default_display_name"],
                row["default_color"],
                row["created_at"],
                row["updated_at"],
            )
