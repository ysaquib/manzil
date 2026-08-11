"""AD-1: the admin router's gate and its ledger (DESIGN §20 v3.39).

The admin router is the one place in the API where tenant isolation stops being
RLS's job — every read here deliberately crosses Hunts the caller is not a
member of. So the tests that matter are the negative ones: who is refused, and
whether a refusal can be outlived by a token.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

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
    names = {row["name"] for row in hunts.json()["items"]}
    assert "Collab Hunt" in names

    summary = await as_admin.get("/v1/admin/summary")
    assert summary.status_code == 200
    assert summary.json()["hunts"] >= 1
    assert summary.json()["tier3_credits_allowance"] == 5000

    feed = await as_admin.get(f"/v1/admin/hunts/{collab_hunt['hunt_id']}/activity")
    assert feed.status_code == 200, feed.text


async def test_hunt_list_pages_and_searches_on_the_server(
    as_admin: AsyncClient, collab_hunt, db_pool
) -> None:
    """The table is paged by the database, not by the browser.

    `total` counts the whole match rather than the page, because a pager with
    no count cannot render a last-page button — and a client that has to fetch
    everything to learn the count is the thing this replaced.
    """
    everything = await as_admin.get("/v1/admin/hunts")
    assert everything.status_code == 200
    total = everything.json()["total"]
    assert total >= 1
    assert len(everything.json()["items"]) == total

    first = await as_admin.get("/v1/admin/hunts?limit=1&offset=0")
    assert first.status_code == 200
    assert len(first.json()["items"]) == 1
    # The count describes the match, not the slice.
    assert first.json()["total"] == total

    # Paging is disjoint: page 2 is not page 1 again.
    if total > 1:
        second = await as_admin.get("/v1/admin/hunts?limit=1&offset=1")
        assert second.json()["items"][0]["hunt_id"] != first.json()["items"][0]["hunt_id"]

    # Past the end is an empty page that still knows the size of the match —
    # the branch where `total` cannot ride along on a row.
    past = await as_admin.get(f"/v1/admin/hunts?limit=10&offset={total + 50}")
    assert past.status_code == 200
    assert past.json()["items"] == []
    assert past.json()["total"] == total

    searched = await as_admin.get("/v1/admin/hunts?search=Collab")
    assert searched.status_code == 200
    assert {row["name"] for row in searched.json()["items"]} == {"Collab Hunt"}
    assert searched.json()["total"] == 1

    # Owner name is searchable too, which is why the frontend must not re-filter
    # the results by label.
    owner_name = await db_pool.fetchval(
        "select up.default_display_name from hunts h "
        "join user_profiles up on up.user_id = h.owner_id where h.id = $1",
        UUID(collab_hunt["hunt_id"]),
    )
    if owner_name:
        by_owner = await as_admin.get(f"/v1/admin/hunts?search={owner_name}")
        assert collab_hunt["hunt_id"] in {r["hunt_id"] for r in by_owner.json()["items"]}

    missing = await as_admin.get("/v1/admin/hunts?search=zzzznotahunt")
    assert missing.json() == {"items": [], "total": 0}

    # The page size has a ceiling for the same reason the typeahead does.
    assert (await as_admin.get("/v1/admin/hunts?limit=5000")).status_code == 422
    assert (await as_admin.get("/v1/admin/hunts?offset=-1")).status_code == 422


async def test_hunt_options_refuses_to_enumerate_the_table(
    as_admin: AsyncClient, collab_hunt
) -> None:
    """The floor is the endpoint's, not the picker's.

    A Hunt picker that could ask for "everything" would ship an installation's
    whole Hunt table to a browser to render a dropdown. Two characters is a
    422 no matter how the frontend is written, and the page size is capped.
    """
    assert (await as_admin.get("/v1/admin/hunts/options?q=Co")).status_code == 422
    assert (await as_admin.get("/v1/admin/hunts/options")).status_code == 422
    assert (await as_admin.get("/v1/admin/hunts/options?q=Collab&limit=500")).status_code == 422

    found = await as_admin.get("/v1/admin/hunts/options?q=Collab")
    assert found.status_code == 200, found.text
    assert collab_hunt["hunt_id"] in {row["hunt_id"] for row in found.json()}
    # Suggestions only — the roll-ups behind the table cost five subqueries per
    # row and nothing in a dropdown reads them.
    assert set(found.json()[0]) == {"hunt_id", "name", "owner_name"}

    missing = await as_admin.get("/v1/admin/hunts/options?q=zzzznotahunt")
    assert missing.status_code == 200
    assert missing.json() == []


async def test_hunt_options_refuses_a_non_admin(as_nobody: AsyncClient) -> None:
    response = await as_nobody.get("/v1/admin/hunts/options?q=Collab")
    assert response.status_code == 403
    assert response.json()["code"] == "not_site_admin"


# ── Hunt management ──────────────────────────────────────────────────────────


async def test_hunt_management_lists_transfer_targets_and_live_blockers(
    as_admin: AsyncClient, collab_hunt, seeded_users
) -> None:
    response = await as_admin.get(f"/v1/admin/hunts/{collab_hunt['hunt_id']}/management")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "Collab Hunt"
    assert body["caller_is_member"] is False
    by_id = {member["user_id"]: member for member in body["members"]}
    assert by_id[seeded_users["owner"].user_id]["role"] == "owner"
    assert by_id[seeded_users["member"].user_id]["display_name"]
    assert isinstance(body["deletion_blockers"], list)


async def test_admin_transfers_hunt_ownership_atomically_and_audits_it(
    as_admin: AsyncClient, collab_hunt, db_pool, seeded_users
) -> None:
    hunt_id = UUID(collab_hunt["hunt_id"])
    old_owner = UUID(seeded_users["owner"].user_id)
    new_owner = UUID(seeded_users["member"].user_id)
    try:
        response = await as_admin.post(
            f"/v1/admin/hunts/{hunt_id}/transfer-ownership",
            json={"new_owner_id": str(new_owner)},
        )
        assert response.status_code == 200, response.text
        assert (
            await db_pool.fetchval("select owner_id from hunts where id=$1", hunt_id) == new_owner
        )
        roles = await db_pool.fetch(
            "select user_id, role::text from hunt_members where hunt_id=$1", hunt_id
        )
        by_user = {row["user_id"]: row["role"] for row in roles}
        assert by_user[new_owner] == "owner"
        assert by_user[old_owner] == "curator"

        audit = await db_pool.fetchrow(
            "select action, target_label, before, after from admin_audit_log "
            "where target_id=$1 order by occurred_at desc limit 1",
            hunt_id,
        )
        assert audit["action"] == "hunt.ownership.transfer"
        assert audit["target_label"] == "Collab Hunt"
    finally:
        await db_pool.execute(
            "select transfer_hunt_ownership($1::uuid, $2::uuid)", hunt_id, old_owner
        )


async def test_admin_permanently_deletes_a_hunt_but_keeps_global_property_truth(
    as_admin: AsyncClient, db_pool, seeded_users
) -> None:
    owner_id = UUID(seeded_users["owner"].user_id)
    admin_id = UUID(seeded_users["outsider"].user_id)
    hunt_id = await db_pool.fetchval(
        "insert into hunts(name, owner_id) values('Disposable Hunt', $1) returning id",
        owner_id,
    )
    property_id = await db_pool.fetchval(
        "insert into properties(name, canonical_address) "
        "values('Shared Building', '1 Durable St') returning id"
    )
    listing_id = await db_pool.fetchval(
        "insert into hunt_listings(hunt_id, property_id, added_by) values($1, $2, $3) returning id",
        hunt_id,
        property_id,
        owner_id,
    )
    await db_pool.execute(
        "insert into jobs(hunt_id, hunt_listing_id, type, state, payload) "
        "values($1, $2, 'ingest', 'done', '{}'::jsonb)",
        hunt_id,
        listing_id,
    )
    try:
        wrong = await as_admin.request(
            "DELETE",
            f"/v1/admin/hunts/{hunt_id}",
            json={"confirmation_name": "Disposable"},
        )
        assert wrong.status_code == 422
        assert wrong.json()["code"] == "hunt_confirmation_mismatch"

        deleted = await as_admin.request(
            "DELETE",
            f"/v1/admin/hunts/{hunt_id}",
            json={"confirmation_name": "Disposable Hunt"},
        )
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["listings"] == 1
        assert await db_pool.fetchval("select count(*) from hunts where id=$1", hunt_id) == 0
        assert (
            await db_pool.fetchval("select count(*) from properties where id=$1", property_id) == 1
        )

        tombstone = await db_pool.fetchrow(
            "select label, deleted_by from deletion_tombstones "
            "where entity_type='hunt' and entity_id=$1 order by deleted_at desc limit 1",
            hunt_id,
        )
        assert tombstone["label"] == "Disposable Hunt"
        assert tombstone["deleted_by"] == admin_id
        audit = await db_pool.fetchrow(
            "select action, target_label from admin_audit_log "
            "where target_id=$1 order by occurred_at desc limit 1",
            hunt_id,
        )
        assert audit["action"] == "hunt.permanent_delete"
        assert audit["target_label"] == "Disposable Hunt"
    finally:
        await db_pool.execute("delete from hunts where id=$1", hunt_id)
        await db_pool.execute("delete from deletion_tombstones where hunt_id=$1", hunt_id)
        await db_pool.execute("delete from properties where id=$1", property_id)


async def test_active_job_blocks_admin_hunt_deletion(
    as_admin: AsyncClient, db_pool, seeded_users
) -> None:
    hunt_id = await db_pool.fetchval(
        "insert into hunts(name, owner_id) values('Busy Hunt', $1) returning id",
        seeded_users["owner"].user_id,
    )
    await db_pool.execute(
        "insert into jobs(hunt_id, type, state, payload) "
        "values($1, 'refresh', 'queued', '{}'::jsonb)",
        hunt_id,
    )
    try:
        response = await as_admin.request(
            "DELETE",
            f"/v1/admin/hunts/{hunt_id}",
            json={"confirmation_name": "Busy Hunt"},
        )
        assert response.status_code == 409
        assert response.json()["code"] == "hunt_deletion_blocked"
        assert "1 active Job" in response.json()["detail"]
        assert await db_pool.fetchval("select count(*) from hunts where id=$1", hunt_id) == 1
    finally:
        await db_pool.execute("delete from hunts where id=$1", hunt_id)
        await db_pool.execute("delete from deletion_tombstones where hunt_id=$1", hunt_id)


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
