from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from manzil_api.analytics import calendar_window
from manzil_api.main import create_app

pytestmark = pytest.mark.asyncio


async def test_calendar_window_uses_local_midnight_across_dst() -> None:
    start, end, labels = calendar_window(
        2,
        "America/Detroit",
        now=datetime(2026, 11, 1, 6, 30, tzinfo=UTC),
    )
    assert labels == [date(2026, 10, 31), date(2026, 11, 1)]
    assert start == datetime(2026, 10, 31, 4, 0, tzinfo=UTC)
    assert end == datetime(2026, 11, 2, 5, 0, tzinfo=UTC)


async def _client(db_pool, identity) -> AsyncClient:  # type: ignore[no-untyped-def]
    app = create_app()
    app.state.db_pool = db_pool
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {identity.token}"},
    )


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
