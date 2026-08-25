from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from local_supabase import LOCAL_JWT_SECRET, LOCAL_SUPABASE_URL
from manzil_api.analytics import calendar_window
from manzil_api.main import create_app

pytestmark = pytest.mark.asyncio


def _demo_bearer_token(subject: UUID, generation: int) -> str:
    """A minted-demo-token stand-in matching the profile the verifier pins.

    See `test_demo_api.demo_token` for the same shape; duplicated locally
    rather than imported so this HTTP-level suite does not reach across test
    modules for a JWT-signing helper.
    """
    now = int(datetime.now(UTC).timestamp())
    claims = {
        "sub": str(subject),
        "aud": "authenticated",
        "role": "authenticated",
        "iss": f"{LOCAL_SUPABASE_URL}/auth/v1",
        "iat": now,
        "exp": now + 900,
        "manzil_demo": True,
        "manzil_demo_gen": generation,
    }
    return jwt.encode(claims, LOCAL_JWT_SECRET, algorithm="HS256")


async def test_calendar_window_uses_local_midnight_across_dst() -> None:
    start, end, labels = calendar_window(
        2,
        "America/Detroit",
        now=datetime(2026, 11, 1, 6, 30, tzinfo=UTC),
    )
    assert labels == [date(2026, 10, 31), date(2026, 11, 1)]
    assert start == datetime(2026, 10, 31, 4, 0, tzinfo=UTC)
    assert end == datetime(2026, 11, 2, 5, 0, tzinfo=UTC)


async def _client_with_bearer(db_pool, token: str) -> AsyncClient:  # type: ignore[no-untyped-def]
    app = create_app()
    app.state.db_pool = db_pool
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    )


async def _client(db_pool, identity) -> AsyncClient:  # type: ignore[no-untyped-def]
    return await _client_with_bearer(db_pool, identity.token)


async def test_hunt_statistics_zero_fill_detroit_days_and_retain_deleted_usage(
    db_pool, collab_hunt, seeded_users
) -> None:
    hunt_id = UUID(collab_hunt["hunt_id"])
    listing_id = UUID(collab_hunt["owner_listing_id"])
    visible_id, deleted_id = uuid4(), uuid4()
    actor = UUID(seeded_users["owner"].user_id)
    zone = ZoneInfo("America/Detroit")
    today = datetime.now(zone).date()
    yesterday = today - timedelta(days=1)
    visible_created = datetime.combine(yesterday, time(23, 30), tzinfo=zone)
    visible_finished = datetime.combine(today, time(0, 30), tzinfo=zone)
    deleted_created = datetime.combine(today, time(1, 0), tzinfo=zone)
    deleted_finished = datetime.combine(today, time(1, 5), tzinfo=zone)
    await db_pool.execute(
        """
        insert into jobs (
            id, hunt_id, hunt_listing_id, type, state, cost_actual_usd,
            created_at, started_at, finished_at
        ) values ($1, $2, $3, 'ingest', 'done', 0.0100, $4, $4, $5)
        """,
        visible_id,
        hunt_id,
        listing_id,
        visible_created,
        visible_finished,
    )
    await db_pool.execute(
        """
        insert into jobs (
            id, hunt_id, hunt_listing_id, type, state, cost_actual_usd,
            created_at, started_at, finished_at,
            deleted_at, deleted_by, deleted_from_state
        ) values ($1, $2, $3, 'ingest', 'deleted', 0.0200, $4, $4, $5,
           $5, $6, 'failed')
        """,
        deleted_id,
        hunt_id,
        listing_id,
        deleted_created,
        deleted_finished,
        actor,
    )
    await db_pool.execute(
        """
        insert into job_stage_costs (
            job_id, stage, llm_calls, llm_cost_usd, input_tokens, output_tokens,
            fetch_calls, fetch_cost_usd, fetch_calls_by_provider, updated_at
        ) values
          ($1, 'SCORE', 2, 0.001, 100, 20, 0, 0, '{}', $3),
          ($2, 'FETCH', 0, 0, 0, 0, 1, 0.0015, '{"brightdata":1}', $4)
        """,
        visible_id,
        deleted_id,
        visible_finished,
        deleted_finished,
    )
    try:
        async with await _client(db_pool, seeded_users["member"]) as client:
            response = await client.get(
                f"/v1/hunts/{hunt_id}/statistics?days=7&timezone=America%2FDetroit"
            )
            assert response.status_code == 200, response.text
            report = response.json()

            assert len(report["daily"]) == 7
            assert report["daily"][-1]["day"] == today.isoformat()
            prior_point = next(
                point for point in report["daily"] if point["day"] == yesterday.isoformat()
            )
            today_point = next(
                point for point in report["daily"] if point["day"] == today.isoformat()
            )
            assert prior_point["listing_submissions"] == 1
            assert prior_point["billed_cost_usd"] == 0
            assert today_point["billed_cost_usd"] == 0.03
            assert today_point["llm_calls"] == 2
            assert today_point["deleted_cost_usd"] == 0.02
            assert today_point["jobs_failed"] == 1
            assert today_point["fetch_calls"] == 1
            assert report["summary"]["listing_submissions"] == 2
            assert any(
                point["listing_submissions"] == 0 and point["billed_cost_usd"] == 0
                for point in report["daily"]
            )

            invalid = await client.get(
                f"/v1/hunts/{hunt_id}/statistics?days=7&timezone=Not%2FAZone"
            )
            assert invalid.status_code == 422
            invalid_days = await client.get(f"/v1/hunts/{hunt_id}/statistics?days=8")
            assert invalid_days.status_code == 422

        async with await _client(db_pool, seeded_users["outsider"]) as outsider:
            assert (await outsider.get(f"/v1/hunts/{hunt_id}/statistics")).status_code == 404

        await db_pool.execute(
            "insert into site_admins (user_id) values ($1) on conflict do nothing",
            UUID(seeded_users["outsider"].user_id),
        )
        async with await _client(db_pool, seeded_users["outsider"]) as ghost:
            assert (await ghost.get(f"/v1/hunts/{hunt_id}/statistics")).status_code == 200
    finally:
        await db_pool.execute(
            "delete from site_admins where user_id=$1", UUID(seeded_users["outsider"].user_id)
        )
        await db_pool.execute("delete from jobs where id=any($1::uuid[])", [visible_id, deleted_id])


async def _promote_demo_release(db_pool, hunt_id: UUID) -> UUID:
    """Give the demo session the complete release configuration
    `private.demo_identity()` requires: a display name on every Hunt member,
    Site Admin ownership, and a 'ready' `demo_publications` row -- otherwise
    identity resolves to 'dark', not 'scoped', and every Hunt-scoped read
    404s regardless of `demo_hunt_id`.

    Mirrors `test_demo_guard._select_demo_hunt`, duplicated locally per this
    file's own no-cross-module-imports convention (see `_demo_bearer_token`).
    Returns the Hunt's owner id so the caller can undo the Site Admin grant.
    """
    owner = await db_pool.fetchval("select owner_id from hunts where id = $1", hunt_id)
    await db_pool.execute(
        """
        update hunt_members
           set display_name = coalesce(display_name, 'Demo collaborator')
         where hunt_id = $1
        """,
        hunt_id,
    )
    await db_pool.execute(
        "insert into site_admins (user_id) values ($1) on conflict do nothing", owner
    )
    generation = await db_pool.fetchval("select demo_generation from site_settings")
    release = await db_pool.fetchval(
        """
        insert into private.demo_publications
            (hunt_id, requested_by, state, expected_generation, source_fingerprint,
             published_at, finished_at)
        values ($1, $2, 'ready', $3, 'statistics-test', now(), now())
        returning id
        """,
        hunt_id,
        owner,
        generation,
    )
    await db_pool.execute(
        "update site_settings set demo_enabled = true, demo_hunt_id = $1, demo_release_id = $2",
        hunt_id,
        release,
    )
    return owner


async def test_hunt_statistics_visible_to_a_demo_session(db_pool, collab_hunt) -> None:
    """DESIGN §13.2 promises Statistics to every Hunt member with no demo
    carve-out, and the Demo Account is a member (Curator) of the Demo Hunt.

    Regression for the endpoint hand-rolling its own `hunt_members`/
    `site_admins` membership check on the raw pool instead of `ValidHunt`'s
    ordinary RLS-scoped read, which 404'd every demo session unconditionally
    regardless of which Hunt was selected as the Demo Hunt (§20 v3.105).
    """
    hunt_id = UUID(collab_hunt["hunt_id"])
    listing_id = UUID(collab_hunt["owner_listing_id"])
    job_id = uuid4()
    demo_subject = uuid4()
    now = datetime.now(UTC)
    await db_pool.execute(
        """
        insert into jobs (id, hunt_id, hunt_listing_id, type, state, cost_actual_usd,
                           created_at, started_at, finished_at)
        values ($1, $2, $3, 'ingest', 'done', 0.0500, $4, $4, $4)
        """,
        job_id,
        hunt_id,
        listing_id,
        now,
    )
    markers = [
        dict(row)
        for row in await db_pool.fetch("select user_id, created_by, note from demo_accounts")
    ]
    owner_id: UUID | None = None
    try:
        await db_pool.execute("delete from demo_accounts")
        await db_pool.execute(
            "insert into demo_accounts (user_id, note) values ($1, 'statistics test')",
            demo_subject,
        )
        owner_id = await _promote_demo_release(db_pool, hunt_id)
        generation = await db_pool.fetchval("select demo_generation from site_settings")
        token = _demo_bearer_token(demo_subject, generation)

        async with await _client_with_bearer(db_pool, token) as demo_client:
            response = await demo_client.get(f"/v1/hunts/{hunt_id}/statistics?days=7")
            assert response.status_code == 200, response.text
            assert response.json()["summary"]["billed_cost_usd"] == 0.05

        # A demo session is confined to the one selected Demo Hunt, same as
        # every other Hunt-scoped read -- statistics must not leak a second.
        # Owned by an unrelated id, never the demo subject itself: a demo
        # principal may not hold a stored Hunt membership (ownership included).
        other_hunt_id = await db_pool.fetchval(
            "insert into hunts (name, owner_id) values ('Not the Demo Hunt', $1) returning id",
            uuid4(),
        )
        try:
            async with await _client_with_bearer(db_pool, token) as demo_client:
                out_of_scope = await demo_client.get(f"/v1/hunts/{other_hunt_id}/statistics")
                assert out_of_scope.status_code == 404
        finally:
            await db_pool.execute("delete from hunts where id=$1", other_hunt_id)
    finally:
        await db_pool.execute("delete from jobs where id=$1", job_id)
        await db_pool.execute(
            "update site_settings set demo_enabled = false, demo_hunt_id = null,"
            " demo_release_id = null where demo_hunt_id = $1",
            hunt_id,
        )
        await db_pool.execute("delete from private.demo_publications where hunt_id = $1", hunt_id)
        if owner_id is not None:
            await db_pool.execute("delete from site_admins where user_id = $1", owner_id)
        await db_pool.execute("delete from demo_accounts")
        for marker in markers:
            await db_pool.execute(
                "insert into demo_accounts (user_id, created_by, note) values ($1, $2, $3)",
                marker["user_id"],
                marker["created_by"],
                marker["note"],
            )
