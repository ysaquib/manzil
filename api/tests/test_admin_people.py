"""AD-3: People management.

The interesting tests are the refusals. Everything else here is CRUD over
`auth.users`, but deleting the wrong account takes a Hunt and its entire
history with it, and there is no undo.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from manzil_api.main import create_app

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def admin_app(db_pool):  # type: ignore[no-untyped-def]
    app = create_app()
    app.state.db_pool = db_pool
    return app


@pytest_asyncio.fixture
async def as_admin(admin_app, db_pool, seeded_users) -> AsyncIterator[AsyncClient]:
    identity = seeded_users["outsider"]
    await db_pool.execute(
        "insert into site_admins (user_id) values ($1) on conflict do nothing", identity.user_id
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app=admin_app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {identity.token}"},
        ) as client:
            yield client
    finally:
        await db_pool.execute("delete from site_admins where user_id = $1", identity.user_id)


# ── the roster ───────────────────────────────────────────────────────────────


async def test_the_roster_answers_who_they_are_and_what_they_hold(
    as_admin: AsyncClient, collab_hunt, seeded_users
) -> None:
    response = await as_admin.get("/v1/admin/people")
    assert response.status_code == 200
    by_email = {row["email"]: row for row in response.json()}

    owner = by_email["owner@test.manzil"]
    assert owner["owns"] >= 1
    assert owner["hunts"] >= 1
    assert owner["confirmed"] is True
    assert owner["suspended"] is False

    # The admin flag is read from site_admins, not guessed from a role.
    assert by_email["outsider@test.manzil"]["is_site_admin"] is True


async def test_search_matches_email_or_display_name(as_admin: AsyncClient, collab_hunt) -> None:
    hit = await as_admin.get("/v1/admin/people?search=curator@test")
    assert [row["email"] for row in hit.json()] == ["curator@test.manzil"]

    miss = await as_admin.get("/v1/admin/people?search=nobody-by-that-name")
    assert miss.json() == []


async def test_detail_carries_memberships_and_what_blocks_deletion(
    as_admin: AsyncClient, collab_hunt, seeded_users
) -> None:
    response = await as_admin.get(f"/v1/admin/people/{seeded_users['owner'].user_id}")
    assert response.status_code == 200
    detail = response.json()

    hunts = {m["hunt_name"]: m["role"] for m in detail["memberships"]}
    assert hunts.get("Collab Hunt") == "owner"
    # Containment, not equality: this account may own other Hunts in a shared
    # development database, and asserting the exact list would be testing the
    # fixture's isolation rather than the endpoint.
    assert "Collab Hunt" in [m["hunt_name"] for m in detail["blocking_owned_hunts"]]


async def test_an_unknown_account_is_404(as_admin: AsyncClient) -> None:
    response = await as_admin.get(f"/v1/admin/people/{uuid4()}")
    assert response.status_code == 404
    assert response.json()["code"] == "person_not_found"


# ── the refusals ─────────────────────────────────────────────────────────────


async def test_deleting_a_hunt_owner_is_refused_and_says_which_hunt(
    as_admin: AsyncClient, collab_hunt, seeded_users, db_pool
) -> None:
    """The cascade from auth.users would take the Hunt, its Listings, Visits and
    Jobs. The refusal names the Hunts because an operator told only "this
    failed" goes looking; one told which Hunts is a click from the fix."""
    owner_id = seeded_users["owner"].user_id
    response = await as_admin.delete(f"/v1/admin/people/{owner_id}")

    assert response.status_code == 409
    assert response.json()["code"] == "person_owns_a_hunt"
    assert "Collab Hunt" in response.json()["detail"]

    # And the account is untouched.
    assert await db_pool.fetchval("select count(*) from auth.users where id = $1", owner_id) == 1


async def test_the_transfer_unblocks_the_delete(
    as_admin: AsyncClient, collab_hunt, seeded_users, db_pool
) -> None:
    """The inline fix the refusal points at: hand the Hunt to somebody else and
    the same account becomes deletable. Ownership moves through
    `transfer_hunt_ownership`, so exactly one owner exists throughout."""
    owner_id = seeded_users["owner"].user_id
    curator_id = seeded_users["curator"].user_id
    hunt_id = collab_hunt["hunt_id"]

    moved = await as_admin.put(
        f"/v1/admin/people/{curator_id}/memberships",
        json={"hunt_id": str(hunt_id), "role": "owner"},
    )
    assert moved.status_code == 200

    roles = {
        str(row["user_id"]): row["role"]
        for row in await db_pool.fetch(
            "select user_id, role::text as role from hunt_members where hunt_id = $1", hunt_id
        )
    }
    assert roles[str(curator_id)] == "owner"
    assert roles[str(owner_id)] != "owner", "the old owner must not still be one"

    # This Hunt no longer blocks the previous owner, and now blocks the new one.
    old = await as_admin.get(f"/v1/admin/people/{owner_id}")
    assert "Collab Hunt" not in [m["hunt_name"] for m in old.json()["blocking_owned_hunts"]]
    new = await as_admin.get(f"/v1/admin/people/{curator_id}")
    assert "Collab Hunt" in [m["hunt_name"] for m in new.json()["blocking_owned_hunts"]]


async def test_removing_the_owner_from_their_own_hunt_is_refused(
    as_admin: AsyncClient, collab_hunt, seeded_users
) -> None:
    response = await as_admin.delete(
        f"/v1/admin/people/{seeded_users['owner'].user_id}/memberships/{collab_hunt['hunt_id']}"
    )
    assert response.status_code == 409
    assert response.json()["code"] == "person_owns_a_hunt"


async def test_an_admin_cannot_delete_or_suspend_themselves(
    as_admin: AsyncClient, seeded_users
) -> None:
    me = seeded_users["outsider"].user_id
    assert (await as_admin.delete(f"/v1/admin/people/{me}")).status_code == 409
    assert (await as_admin.post(f"/v1/admin/people/{me}/suspend")).status_code == 409


async def test_deleting_someone_who_left_work_behind_is_refused_not_a_500(
    as_admin: AsyncClient, collab_hunt, seeded_users, db_pool
) -> None:
    """Eleven columns reference `auth.users` with NO ACTION, so an account that
    ever created a Visit could not be deleted — GoTrue surfaced the raw foreign
    key error as a 502/500 that told the operator nothing.

    The work belongs to the Hunt rather than to the person: a tour is not
    deleted because its creator closed their account, and §9.7's per-member
    roll-up cannot survive its author being nulled. So it is refused, it says
    what blocks it, and it points at the reversible action.
    """
    curator_id = seeded_users["curator"].user_id
    visit_id = await db_pool.fetchval(
        "insert into visits (hunt_id, property_id, created_by, template_version) "
        "values ($1, $2, $3, 1) returning id",
        collab_hunt["hunt_id"],
        collab_hunt["owner_property_id"],
        curator_id,
    )
    try:
        response = await as_admin.delete(f"/v1/admin/people/{curator_id}")

        assert response.status_code == 409
        assert response.json()["code"] == "account_still_referenced"
        detail = response.json()["detail"]
        assert "visits" in detail
        assert "Suspend" in detail, "the refusal must name the way forward"

        # And the account is untouched.
        assert (
            await db_pool.fetchval("select count(*) from auth.users where id = $1", curator_id) == 1
        )
    finally:
        await db_pool.execute("delete from visits where id = $1", visit_id)


# ── the reversible action ────────────────────────────────────────────────────


async def test_site_admin_provisioning_is_audited(
    as_admin: AsyncClient, db_pool, seeded_users, monkeypatch
) -> None:
    from manzil_api.admin import people

    new_id = uuid4()
    captured: dict = {}

    class AdminAuth:
        def invite_user_by_email(self, email, options):  # type: ignore[no-untyped-def]
            captured.update(email=email, options=options)
            return SimpleNamespace(user=SimpleNamespace(id=str(new_id)))

    monkeypatch.setattr(
        people,
        "_service",
        lambda: SimpleNamespace(auth=SimpleNamespace(admin=AdminAuth())),
    )

    response = await as_admin.post("/v1/admin/people", json={"email": "new-person@example.com"})

    assert response.status_code == 201
    assert captured["email"] == "new-person@example.com"
    assert captured["options"]["redirect_to"].endswith("/auth/reset-password")
    audit = await db_pool.fetchrow(
        "select action, target_id, target_label from admin_audit_log "
        "where admin_user_id = $1 order by occurred_at desc limit 1",
        seeded_users["outsider"].user_id,
    )
    assert audit["action"] == "user.provision"
    assert audit["target_id"] == new_id
    assert audit["target_label"] == "new-person@example.com"


async def test_suspend_and_restore_round_trip(as_admin: AsyncClient, seeded_users, db_pool) -> None:
    """Suspension is the reversible alternative to deletion, and it is an
    auth-level ban rather than a column of ours — a second source of truth for
    "can this person sign in" is exactly what drifts."""
    target = seeded_users["member"].user_id

    suspended = await as_admin.post(f"/v1/admin/people/{target}/suspend")
    assert suspended.status_code == 200
    assert (await as_admin.get(f"/v1/admin/people/{target}")).json()["suspended"] is True

    restored = await as_admin.post(f"/v1/admin/people/{target}/restore")
    assert restored.status_code == 200
    assert (await as_admin.get(f"/v1/admin/people/{target}")).json()["suspended"] is False


async def test_membership_edits_are_recorded_by_the_trigger_and_the_ledger(
    as_admin: AsyncClient, collab_hunt, seeded_users, db_pool
) -> None:
    """Two independent records, on purpose: AD-G's trigger writes what happened
    to the Hunt, and the admin ledger writes that an operator did it."""
    target = seeded_users["member"].user_id
    hunt_id = collab_hunt["hunt_id"]

    await as_admin.put(
        f"/v1/admin/people/{target}/memberships",
        json={"hunt_id": str(hunt_id), "role": "curator"},
    )

    domain = await db_pool.fetchrow(
        "select action, role::text as role from hunt_member_history "
        "where hunt_id = $1 and user_id = $2 order by recorded_at desc limit 1",
        hunt_id,
        target,
    )
    assert (domain["action"], domain["role"]) == ("role_changed", "curator")

    ledger = await db_pool.fetchrow(
        "select action, before, after from admin_audit_log "
        "where admin_user_id = $1 order by occurred_at desc limit 1",
        seeded_users["outsider"].user_id,
    )
    assert ledger["action"] == "membership.set"
    assert '"member"' in ledger["before"]
    assert '"curator"' in ledger["after"]


async def test_deleting_an_account_that_owns_nothing_succeeds_and_is_audited(
    as_admin: AsyncClient, db_pool, seeded_users
) -> None:
    """The happy path, kept honest: create a throwaway account, delete it, and
    confirm the ledger recorded the email — an id whose row is gone tells a
    reader nothing."""
    from local_supabase import LOCAL_SERVICE_ROLE_KEY, LOCAL_SUPABASE_URL
    from manzil_api.config import get_settings
    from manzil_api.database import create_service_client

    assert LOCAL_SERVICE_ROLE_KEY and LOCAL_SUPABASE_URL
    email = f"disposable-{uuid4().hex[:8]}@test.manzil"
    # Created through GoTrue rather than raw SQL: an auth.users row inserted by
    # hand is missing the identity records GoTrue expects, and it refuses to
    # delete what it did not fully construct.
    created = create_service_client(get_settings()).auth.admin.create_user(
        {"email": email, "password": "disposable-password", "email_confirm": True}
    )
    user_id = created.user.id

    response = await as_admin.delete(f"/v1/admin/people/{user_id}")
    assert response.status_code == 204
    assert await db_pool.fetchval("select count(*) from auth.users where id = $1", user_id) == 0

    row = await db_pool.fetchrow(
        "select action, target_label from admin_audit_log "
        "where admin_user_id = $1 order by occurred_at desc limit 1",
        seeded_users["outsider"].user_id,
    )
    assert row["action"] == "user.delete"
    assert row["target_label"] == email


# ── the gate ─────────────────────────────────────────────────────────────────


async def test_a_non_admin_is_refused_everywhere(admin_app, seeded_users, collab_hunt) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=admin_app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {seeded_users['member'].token}"},
    ) as client:
        target = seeded_users["owner"].user_id
        assert (await client.get("/v1/admin/people")).status_code == 403
        assert (await client.get(f"/v1/admin/people/{target}")).status_code == 403
        assert (
            await client.post("/v1/admin/people", json={"email": "blocked@example.com"})
        ).status_code == 403
        assert (await client.post(f"/v1/admin/people/{target}/suspend")).status_code == 403
        assert (await client.delete(f"/v1/admin/people/{target}")).status_code == 403
