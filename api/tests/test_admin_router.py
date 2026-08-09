"""AD-1: the admin router's gate and its ledger (DESIGN §20 v3.39).

The admin router is the one place in the API where tenant isolation stops being
RLS's job — every read here deliberately crosses Hunts the caller is not a
member of. So the tests that matter are the negative ones: who is refused, and
whether a refusal can be outlived by a token.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from manzil_api.main import create_app

pytestmark = pytest.mark.asyncio


def _client(app, identity) -> AsyncClient:  # type: ignore[no-untyped-def]
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {identity.token}"},
    )


@pytest_asyncio.fixture
async def admin_app(db_pool):  # type: ignore[no-untyped-def]
    """The API tests run without a lifespan, so the pool the admin routes read
    through has to be attached by hand."""
    app = create_app()
    app.state.db_pool = db_pool
    return app


@pytest_asyncio.fixture
async def as_admin(admin_app, db_pool, seeded_users) -> AsyncIterator[AsyncClient]:
    """`outsider` is deliberately the admin: it belongs to no Hunt, so every
    passing read below is a genuine cross-tenant read rather than a membership
    that happened to work."""
    identity = seeded_users["outsider"]
    await db_pool.execute(
        "insert into site_admins (user_id) values ($1) on conflict do nothing", identity.user_id
    )
    try:
        async with _client(admin_app, identity) as client:
            yield client
    finally:
        await db_pool.execute("delete from site_admins where user_id = $1", identity.user_id)
        # Audit rows are deliberately NOT cleaned up: the table refuses deletes,
        # which is the property under test. A log that tests can erase is not one.


@pytest_asyncio.fixture
async def as_nobody(admin_app, seeded_users) -> AsyncIterator[AsyncClient]:
    async with _client(admin_app, seeded_users["member"]) as client:
        yield client


# ── the gate ─────────────────────────────────────────────────────────────────


async def test_me_answers_honestly_instead_of_refusing(as_nobody: AsyncClient) -> None:
    """The frontend calls this on every load to decide whether to render the nav
    entry. A 403 here would put an error in every non-admin user's console."""
    response = await as_nobody.get("/v1/admin/me")
    assert response.status_code == 200
    assert response.json()["is_site_admin"] is False


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/v1/admin/summary"),
        ("get", "/v1/admin/hunts"),
        ("get", "/v1/admin/audit"),
        ("post", "/v1/admin/admins"),
        ("delete", f"/v1/admin/admins/{uuid4()}"),
    ],
)
async def test_every_other_route_refuses_a_non_admin(
    as_nobody: AsyncClient, method: str, path: str
) -> None:
    call = getattr(as_nobody, method)
    response = (
        await call(path, json={"user_id": str(uuid4())}) if method == "post" else await call(path)
    )
    assert response.status_code == 403
    assert response.json()["code"] == "not_site_admin"


async def test_revoking_admin_takes_effect_without_a_new_token(
    as_admin: AsyncClient, db_pool, seeded_users
) -> None:
    """The reason the gate hits the database instead of a JWT claim. A claim is
    fixed at sign-in, so a revoked admin would keep their access until the token
    expired — the one case where being slow to notice is unacceptable. The token
    below never changes; only the row does."""
    assert (await as_admin.get("/v1/admin/summary")).status_code == 200

    await db_pool.execute(
        "delete from site_admins where user_id = $1", seeded_users["outsider"].user_id
    )
    assert (await as_admin.get("/v1/admin/summary")).status_code == 403


# ── reads ────────────────────────────────────────────────────────────────────


async def test_an_admin_reads_across_hunts_they_do_not_belong_to(
    as_admin: AsyncClient, collab_hunt, db_pool, seeded_users
) -> None:
    membership = await db_pool.fetchval(
        "select count(*) from hunt_members where user_id = $1", seeded_users["outsider"].user_id
    )
    assert membership == 0, "this test is meaningless if the admin is a member of anything"

    hunts = await as_admin.get("/v1/admin/hunts")
    assert hunts.status_code == 200
    names = {row["name"] for row in hunts.json()}
    assert "Collab Hunt" in names

    summary = await as_admin.get("/v1/admin/summary")
    assert summary.status_code == 200
    assert summary.json()["hunts"] >= 1
    assert summary.json()["tier3_credits_allowance"] == 5000

    feed = await as_admin.get(f"/v1/admin/hunts/{collab_hunt['hunt_id']}/activity")
    assert feed.status_code == 200, feed.text


# ── the ledger ───────────────────────────────────────────────────────────────


async def test_granting_admin_leaves_an_audit_row(
    as_admin: AsyncClient, db_pool, seeded_users
) -> None:
    target = seeded_users["curator"].user_id
    try:
        granted = await as_admin.post(
            "/v1/admin/admins", json={"user_id": target, "note": "oncall"}
        )
        assert granted.status_code == 201
        assert granted.json()["is_site_admin"] is True

        row = await db_pool.fetchrow(
            "select action, target_type, target_id, after from admin_audit_log "
            "where admin_user_id = $1 order by occurred_at desc limit 1",
            seeded_users["outsider"].user_id,
        )
        assert row["action"] == "admin.grant"
        assert str(row["target_id"]) == target
        assert row["target_type"] == "user"
    finally:
        await db_pool.execute("delete from site_admins where user_id = $1", target)


async def test_an_admin_cannot_revoke_themselves(as_admin: AsyncClient, seeded_users) -> None:
    response = await as_admin.delete(f"/v1/admin/admins/{seeded_users['outsider'].user_id}")
    assert response.status_code == 409
    assert response.json()["code"] == "cannot_revoke_self"


async def test_the_primordial_admin_is_refused_with_a_useful_status(
    as_admin: AsyncClient, db_pool, seeded_users, no_primordial_admin
) -> None:
    """The database refuses this too — the route only exists to return 409
    rather than surfacing a raw constraint error."""
    target = seeded_users["curator"].user_id
    await db_pool.execute(
        "insert into site_admins (user_id, is_primordial) values ($1, true)", target
    )
    try:
        response = await as_admin.delete(f"/v1/admin/admins/{target}")
        assert response.status_code == 409
        assert response.json()["code"] == "primordial_admin_protected"
        assert (
            await db_pool.fetchval("select count(*) from site_admins where user_id = $1", target)
            == 1
        )
    finally:
        await db_pool.execute(
            "alter table site_admins disable trigger site_admins_protect_primordial"
        )
        await db_pool.execute("delete from site_admins where user_id = $1", target)
        await db_pool.execute(
            "alter table site_admins enable trigger site_admins_protect_primordial"
        )


async def test_the_audit_log_cannot_be_rewritten_even_by_the_writer(
    as_admin: AsyncClient, db_pool, seeded_users
) -> None:
    """RLS cannot express this: the admin router runs as service_role, which
    bypasses RLS entirely and is therefore the only caller with the reach to
    edit history here. A trigger is the only thing that stops it."""
    target = seeded_users["curator"].user_id
    await as_admin.post("/v1/admin/admins", json={"user_id": target})
    try:
        row_id = await db_pool.fetchval(
            "select id from admin_audit_log where admin_user_id = $1 order by occurred_at desc "
            "limit 1",
            seeded_users["outsider"].user_id,
        )
        assert row_id is not None
        with pytest.raises(Exception, match="append-only"):
            await db_pool.execute(
                "update admin_audit_log set action = 'nothing.happened' where id = $1", row_id
            )
        with pytest.raises(Exception, match="append-only"):
            await db_pool.execute("delete from admin_audit_log where id = $1", row_id)
    finally:
        await db_pool.execute("delete from site_admins where user_id = $1", target)


async def test_clients_cannot_read_the_audit_log_directly(seeded_users) -> None:
    """No SELECT policy: a compromised account must not be able to enumerate
    operator activity. The panel reads it through the service-role router."""
    result = seeded_users["owner"].supabase.table("admin_audit_log").select("*").execute()
    assert result.data == []
