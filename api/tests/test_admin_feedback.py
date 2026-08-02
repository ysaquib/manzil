"""AD-2: the feedback inbox.

`feedback` has had no client SELECT policy since P3-16 — its migration said in
as many words that reads "belong to an operator holding service_role". These
tests assert both halves of that: the admin router can read it, and nobody else
can, including the person who wrote the report.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
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


@pytest_asyncio.fixture
async def report(db_pool, collab_hunt, seeded_users):  # type: ignore[no-untyped-def]
    report_id = await db_pool.fetchval(
        """
        insert into feedback (user_id, category, body, route, hunt_id, app_version, user_agent)
        values ($1, 'wrong_data', 'The all-in price double-counts the amenity fee.',
                '/h/abc/overview?drawer=listing&id=9f31c2', $2, '2.0.108', 'Safari 18.4')
        returning id
        """,
        seeded_users["member"].user_id,
        collab_hunt["hunt_id"],
    )
    yield report_id
    await db_pool.execute("delete from feedback where id = $1", report_id)


async def test_a_report_arrives_new_with_the_context_that_makes_it_reproducible(
    as_admin: AsyncClient, report
) -> None:
    response = await as_admin.get("/v1/admin/feedback?triage=new")
    assert response.status_code == 200
    row = next(r for r in response.json() if r["id"] == str(report))

    assert row["triage"] == "new"
    assert row["category"] == "wrong_data"
    # The route (drawer params included), build and browser are what turn two
    # lines into something a developer can reproduce.
    assert row["route"] == "/h/abc/overview?drawer=listing&id=9f31c2"
    assert row["app_version"] == "2.0.108"
    assert row["user_agent"] == "Safari 18.4"
    # Reporter and Hunt are joined, not stored — so a renamed Hunt reads correctly.
    assert row["reporter_email"] == "member@test.manzil"
    assert row["hunt_name"] == "Collab Hunt"


async def test_triaging_moves_the_report_and_the_counts_together(
    as_admin: AsyncClient, report, db_pool
) -> None:
    before = (await as_admin.get("/v1/admin/feedback/counts")).json()

    patched = await as_admin.patch(f"/v1/admin/feedback/{report}", json={"triage": "actioned"})
    assert patched.status_code == 200
    assert patched.json()["triage"] == "actioned"

    after = (await as_admin.get("/v1/admin/feedback/counts")).json()
    assert after["new"] == before["new"] - 1
    assert after["actioned"] == before["actioned"] + 1

    # Filtering is what the chips do; a triaged report must leave "new".
    still_new = await as_admin.get("/v1/admin/feedback?triage=new")
    assert all(r["id"] != str(report) for r in still_new.json())

    stamped = await db_pool.fetchrow(
        "select triaged_at, triaged_by from feedback where id = $1", report
    )
    assert stamped["triaged_at"] is not None
    assert stamped["triaged_by"] is not None


async def test_triaging_is_audited(as_admin: AsyncClient, report, db_pool, seeded_users) -> None:
    await as_admin.patch(f"/v1/admin/feedback/{report}", json={"triage": "wont_fix"})
    row = await db_pool.fetchrow(
        "select action, target_id, before, after from admin_audit_log "
        "where admin_user_id = $1 order by occurred_at desc limit 1",
        seeded_users["outsider"].user_id,
    )
    assert row["action"] == "feedback.triage"
    assert str(row["target_id"]) == str(report)
    # Before/after is a diff, not a snapshot: what the admin changed.
    assert '"new"' in row["before"]
    assert '"wont_fix"' in row["after"]


async def test_an_unknown_report_is_404_not_a_silent_success(as_admin: AsyncClient) -> None:
    response = await as_admin.patch(f"/v1/admin/feedback/{uuid4()}", json={"triage": "seen"})
    assert response.status_code == 404
    assert response.json()["code"] == "feedback_not_found"


async def test_an_invalid_triage_state_is_rejected(as_admin: AsyncClient, report) -> None:
    response = await as_admin.patch(f"/v1/admin/feedback/{report}", json={"triage": "ignored"})
    assert response.status_code == 422


async def test_not_even_the_reporter_can_read_their_own_report(report, seeded_users) -> None:
    """The posture P3-16 chose deliberately: a feedback table its submitters can
    read is a support inbox nobody built, and the two have very different privacy
    properties once several people share a Hunt."""
    for role in ("member", "owner", "curator"):
        result = seeded_users[role].supabase.table("feedback").select("*").execute()
        assert result.data == [], f"{role} must not read feedback"


async def test_a_non_admin_is_refused_by_the_inbox_routes(
    admin_app, seeded_users, report
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=admin_app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {seeded_users['member'].token}"},
    ) as client:
        assert (await client.get("/v1/admin/feedback")).status_code == 403
        assert (await client.get("/v1/admin/feedback/counts")).status_code == 403
        patched = await client.patch(f"/v1/admin/feedback/{report}", json={"triage": "seen"})
        assert patched.status_code == 403
