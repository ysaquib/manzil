"""AD-5: Jobs, Costs and System.

The queue actions are the ones with teeth — a retry re-queues real work and a
release re-queues everything a dead worker was holding — so the tests are about
what each one refuses as much as what it does.
"""

from __future__ import annotations

import json
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


async def _job(db_pool, collab_hunt, state: str, *, stale: bool = False, cost: float = 0.0):
    return await db_pool.fetchval(
        """
        insert into jobs (hunt_id, hunt_listing_id, type, state, current_stage,
                          cost_actual_usd, locked_at, locked_by)
        values ($1, $2, 'ingest', $3::job_state, 'EXTRACT', $4,
                case when $5 then now() - interval '1 hour' else now() end,
                case when $5 then 'dead-worker' else null end)
        returning id
        """,
        collab_hunt["hunt_id"],
        collab_hunt["owner_listing_id"],
        state,
        cost,
        stale,
    )


# ── Jobs ─────────────────────────────────────────────────────────────────────


async def test_the_queue_is_visible_across_hunts_the_admin_is_not_in(
    as_admin: AsyncClient, db_pool, collab_hunt
) -> None:
    job_id = await _job(db_pool, collab_hunt, "failed", cost=0.0123)
    try:
        response = await as_admin.get("/v1/admin/jobs?state=failed")
        assert response.status_code == 200, response.text
        row = next(job for job in response.json() if job["id"] == str(job_id))
        assert row["hunt_name"] == "Collab Hunt"
        assert row["cost_actual_usd"] == 0.0123
        assert row["stale"] is False

        by_id = await as_admin.get(f"/v1/admin/jobs?search={job_id}&search_mode=id")
        assert [job["id"] for job in by_id.json()] == [str(job_id)]
    finally:
        await db_pool.execute("delete from jobs where id = $1", job_id)


async def test_job_detail_is_complete_but_excludes_private_run_state(
    as_admin: AsyncClient, db_pool, collab_hunt, seeded_users
) -> None:
    job_id = await _job(db_pool, collab_hunt, "failed", cost=0.0123)
    requester = seeded_users["owner"]
    await db_pool.execute(
        """
        update jobs set requested_by=$2, started_at=now() - interval '90 seconds',
               finished_at=now(), plan=$3::jsonb, warnings=$4::jsonb,
               payload=$5::jsonb
         where id=$1
        """,
        job_id,
        requester.user_id,
        json.dumps({"stages": ["FETCH", "EXTRACT"]}),
        json.dumps([{"stage": "FETCH", "code": "partial", "message": "One Source failed"}]),
        json.dumps({"run_state": {"cleaned_text": "private sentinel"}}),
    )
    await db_pool.execute(
        "insert into job_events (job_id, stage, event, detail) "
        "values ($1, 'FETCH', 'completed', '{\"tier\": 3}'::jsonb)",
        job_id,
    )
    await db_pool.execute(
        """
        insert into job_stage_costs (
            job_id, stage, llm_cost_usd, fetch_cost_usd, llm_calls, fetch_calls,
            input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
            fetch_calls_by_provider
        ) values ($1, 'FETCH', 0.002, 0.0015, 2, 1, 101, 22, 11, 3,
                  '{"brightdata": 1}'::jsonb)
        """,
        job_id,
    )
    try:
        response = await as_admin.get(f"/v1/admin/jobs/{job_id}")
        assert response.status_code == 200, response.text
        detail = response.json()

        assert detail["plan"] == {"stages": ["FETCH", "EXTRACT"]}
        assert detail["warnings"][0]["code"] == "partial"
        assert detail["requested_by"] == str(requester.user_id)
        assert detail["requested_by_email"] == requester.email
        assert detail["started_at"] is not None
        assert detail["duration_seconds"] == pytest.approx(90, abs=2)
        assert detail["events"][0]["detail"] == {"tier": 3}
        expected_cost_detail = {
            "input_tokens": 101,
            "output_tokens": 22,
            "cache_read_tokens": 11,
            "cache_write_tokens": 3,
            "fetch_calls_by_provider": {"brightdata": 1},
        }
        assert {
            key: detail["stage_costs"][0][key] for key in expected_cost_detail
        } == expected_cost_detail
        assert "payload" not in detail
        assert "cleaned_text" not in response.text
    finally:
        await db_pool.execute("delete from jobs where id = $1", job_id)


async def test_a_stale_lock_is_identified_and_releasable(
    as_admin: AsyncClient, db_pool, collab_hunt
) -> None:
    """A `running` Job whose worker died holds a claim nobody will release, and
    from a per-Hunt Tasks tab it just looks slow."""
    stale_id = await _job(db_pool, collab_hunt, "running", stale=True)
    fresh_id = await _job(db_pool, collab_hunt, "running", stale=False)
    try:
        listed = await as_admin.get("/v1/admin/jobs?stale_only=true")
        ids = {job["id"] for job in listed.json()}
        assert str(stale_id) in ids
        assert str(fresh_id) not in ids, "a live worker's lock must not be swept up"

        released = await as_admin.post("/v1/admin/jobs/release-locks")
        assert released.status_code == 200

        # Re-queued, not failed: nothing is known to be wrong with the work.
        assert (
            await db_pool.fetchval("select state::text from jobs where id = $1", stale_id)
            == "queued"
        )
        assert await db_pool.fetchval("select locked_by from jobs where id = $1", stale_id) is None
        assert (
            await db_pool.fetchval("select state::text from jobs where id = $1", fresh_id)
            == "running"
        )
    finally:
        await db_pool.execute("delete from jobs where id = any($1::uuid[])", [stale_id, fresh_id])


async def test_retry_requeues_and_resets_the_backoff_ladder(
    as_admin: AsyncClient, db_pool, collab_hunt
) -> None:
    job_id = await _job(db_pool, collab_hunt, "failed")
    await db_pool.execute("update jobs set attempts = 3, error = 'blocked' where id = $1", job_id)
    try:
        response = await as_admin.post(f"/v1/admin/jobs/{job_id}/retry")
        assert response.status_code == 200

        row = await db_pool.fetchrow(
            "select state::text as state, attempts, error from jobs where id = $1", job_id
        )
        assert row["state"] == "queued"
        assert row["attempts"] == 0
        assert row["error"] is None
    finally:
        await db_pool.execute("delete from jobs where id = $1", job_id)


async def test_admin_soft_delete_retains_cost_and_audits(
    as_admin: AsyncClient, db_pool, collab_hunt
) -> None:
    job_id = await _job(db_pool, collab_hunt, "done", cost=0.0456)
    response = await as_admin.delete(f"/v1/admin/jobs/{job_id}")
    assert response.status_code == 200
    row = await db_pool.fetchrow(
        "select state::text, deleted_from_state::text, cost_actual_usd from jobs where id=$1",
        job_id,
    )
    assert row["state"] == "deleted"
    assert row["deleted_from_state"] == "done"
    assert float(row["cost_actual_usd"]) == 0.0456
    assert await db_pool.fetchval(
        "select exists(select 1 from admin_audit_log where action='job.delete' and target_id=$1)",
        job_id,
    )
    listed = await as_admin.get("/v1/admin/jobs")
    assert str(job_id) not in {job["id"] for job in listed.json()}


async def test_a_done_job_cannot_be_retried_or_cancelled(
    as_admin: AsyncClient, db_pool, collab_hunt
) -> None:
    job_id = await _job(db_pool, collab_hunt, "done")
    try:
        retried = await as_admin.post(f"/v1/admin/jobs/{job_id}/retry")
        assert retried.status_code == 409
        assert retried.json()["code"] == "job_not_retryable"

        cancelled = await as_admin.post(f"/v1/admin/jobs/{job_id}/cancel")
        assert cancelled.status_code == 409
    finally:
        await db_pool.execute("delete from jobs where id = $1", job_id)


async def test_queue_actions_are_audited(
    as_admin: AsyncClient, db_pool, collab_hunt, seeded_users
) -> None:
    job_id = await _job(db_pool, collab_hunt, "failed")
    try:
        await as_admin.post(f"/v1/admin/jobs/{job_id}/retry")
        row = await db_pool.fetchrow(
            "select action, target_id, before, after from admin_audit_log "
            "where admin_user_id = $1 order by occurred_at desc limit 1",
            seeded_users["outsider"].user_id,
        )
        assert row["action"] == "job.retry"
        assert str(row["target_id"]) == str(job_id)
        assert json.loads(row["after"])["state"] == "queued"
    finally:
        await db_pool.execute("delete from jobs where id = $1", job_id)


async def test_an_unknown_job_is_404(as_admin: AsyncClient) -> None:
    assert (await as_admin.post(f"/v1/admin/jobs/{uuid4()}/retry")).status_code == 404


# ── Costs ────────────────────────────────────────────────────────────────────


async def test_costs_report_splits_the_two_channels_three_ways(
    as_admin: AsyncClient, db_pool, collab_hunt
) -> None:
    """Measured as a delta, not an absolute: `job_stage_costs` is shared with
    every other run against this database, so an equality assertion here would
    be testing the fixture's isolation rather than the report."""

    def find(report: dict, key: str, label: str) -> float:
        bucket = next((b for b in report[key] if b["label"] == label), None)
        return bucket["total_cost_usd"] if bucket else 0.0

    before = (await as_admin.get("/v1/admin/costs?days=30")).json()

    # The Job billed more than its Stage rows account for — the ordinary shape
    # of a Job that retried a Stage, since `job_stage_costs` keeps only the
    # latest attempt while `cost_actual_usd` accumulates (DESIGN §20 v3.80).
    job_id = await _job(db_pool, collab_hunt, "done", cost=0.0500)
    await db_pool.execute(
        "insert into job_stage_costs (job_id, stage, llm_cost_usd, llm_calls, "
        "fetch_cost_usd, fetch_calls, fetch_calls_by_provider) "
        "values ($1, 'EXTRACT', 0.0400, 2, 0.0030, 2, '{\"brightdata\": 2}'::jsonb)",
        job_id,
    )
    try:
        after = (await as_admin.get("/v1/admin/costs?days=30")).json()

        # The two channels stay separable all the way through the report.
        stage = next(b for b in after["by_stage"] if b["label"] == "EXTRACT")
        assert stage["llm_cost_usd"] > 0 and stage["fetch_cost_usd"] > 0

        stage_delta = find(after, "by_stage", "EXTRACT") - find(before, "by_stage", "EXTRACT")
        hunt_delta = find(after, "by_hunt", "Collab Hunt") - find(before, "by_hunt", "Collab Hunt")
        assert stage_delta == pytest.approx(0.043)  # per Stage: the latest attempt
        assert hunt_delta == pytest.approx(0.050)  # per Hunt: what the Job billed

        # The window total is the billed one too, and the shortfall is named
        # rather than dropped — the Hunt's bucket still carries the split.
        assert after["total_cost_usd"] - before["total_cost_usd"] == pytest.approx(0.050)
        # `by_hunt` groups by Hunt *name*, and every test in this file makes a
        # fresh "Collab Hunt" — so this bucket may carry earlier runs too. Assert
        # only that the remainder surfaced at all; the exact arithmetic is pinned
        # against a single Hunt in the next test.
        hunt_bucket = next(b for b in after["by_hunt"] if b["label"] == "Collab Hunt")
        assert hunt_bucket["unattributed_cost_usd"] > 0
        assert hunt_bucket["llm_cost_usd"] > 0 and hunt_bucket["fetch_cost_usd"] > 0

        # By model is derived from the current pin, and the response says so
        # rather than letting a reader mistake it for history.
        assert after["grouped_by_current_pin"] is True
        assert after["by_model"], "stage spend must land under some model"

        assert after["tier3_credits_allowance"] == 5000
        assert after["tier3_credits_used"] - before["tier3_credits_used"] == 2
        assert any(point["fetch_cost_usd"] > 0 for point in after["daily"])
    finally:
        await db_pool.execute("delete from job_stage_costs where job_id = $1", job_id)
        await db_pool.execute("delete from jobs where id = $1", job_id)


async def test_a_hunts_admin_total_matches_what_its_jobs_billed(
    as_admin: AsyncClient, db_pool, collab_hunt
) -> None:
    """The reported bug: Admin priced a Hunt from `job_stage_costs` while the
    Tasks tab summed `jobs.cost_actual_usd`, so every Job that retried a Stage
    made the two screens disagree. Both now read the same accumulator."""

    # Matched by id, never by name: every test in this file creates its own
    # "Collab Hunt", and the page is ordered by spend — so a name match could
    # read a different Hunt before and after the insert.
    async def hunt_row() -> dict:
        page = (await as_admin.get("/v1/admin/hunts?search=Collab Hunt&limit=250")).json()
        return next(row for row in page["items"] if row["hunt_id"] == str(collab_hunt["hunt_id"]))

    before = await hunt_row()

    job_id = await _job(db_pool, collab_hunt, "done", cost=0.0500)
    await db_pool.execute(
        "insert into job_stage_costs (job_id, stage, llm_cost_usd, llm_calls, "
        "fetch_cost_usd, fetch_calls, fetch_calls_by_provider) "
        "values ($1, 'EXTRACT', 0.0400, 2, 0.0030, 2, '{\"brightdata\": 2}'::jsonb)",
        job_id,
    )
    try:
        after = await hunt_row()

        assert after["total_cost_usd"] - before["total_cost_usd"] == pytest.approx(0.050)
        # The split is still the Stage breakdown, and the gap is stated. This row
        # is one Hunt created by this test, so the figures are absolute.
        assert after["llm_cost_usd"] - before["llm_cost_usd"] == pytest.approx(0.040)
        assert after["fetch_cost_usd"] - before["fetch_cost_usd"] == pytest.approx(0.003)
        assert after["unattributed_cost_usd"] == pytest.approx(0.007)
        # The invariant the UI renders against: the parts account for the total.
        assert after["total_cost_usd"] == pytest.approx(
            after["llm_cost_usd"] + after["fetch_cost_usd"] + after["unattributed_cost_usd"]
        )

        # A second Job must add its whole bill once, not once per Stage row —
        # the fan-out the two-CTE shape exists to prevent.
        second = await _job(db_pool, collab_hunt, "done", cost=0.0100)
        await db_pool.execute(
            "insert into job_stage_costs (job_id, stage, llm_cost_usd, llm_calls, "
            "fetch_cost_usd, fetch_calls, fetch_calls_by_provider) values "
            "($1, 'VERIFY', 0.0020, 1, 0, 0, '{}'::jsonb), "
            "($1, 'SCORE', 0.0010, 1, 0, 0, '{}'::jsonb)",
            second,
        )
        try:
            both = await hunt_row()
            assert both["total_cost_usd"] - before["total_cost_usd"] == pytest.approx(0.060)
        finally:
            await db_pool.execute("delete from job_stage_costs where job_id = $1", second)
            await db_pool.execute("delete from jobs where id = $1", second)
    finally:
        await db_pool.execute("delete from job_stage_costs where job_id = $1", job_id)
        await db_pool.execute("delete from jobs where id = $1", job_id)


async def test_the_overview_counts_spend_a_running_job_has_already_made(
    as_admin: AsyncClient, db_pool, collab_hunt
) -> None:
    """`spend_usd_30d` dated Jobs by `finished_at`, so a Job still running — or
    parked at a checkpoint — contributed nothing however much it had spent."""
    before = (await as_admin.get("/v1/admin/summary")).json()["spend_usd_30d"]

    job_id = await _job(db_pool, collab_hunt, "running", cost=0.0250)
    try:
        after = (await as_admin.get("/v1/admin/summary")).json()["spend_usd_30d"]
        assert after - before == pytest.approx(0.025)
    finally:
        await db_pool.execute("delete from jobs where id = $1", job_id)


# ── System ───────────────────────────────────────────────────────────────────


async def test_system_reports_pins_and_key_presence_but_never_a_value(
    as_admin: AsyncClient, db_pool
) -> None:
    await db_pool.execute(
        """
        insert into worker_heartbeats (worker_id, mode, started_at, last_seen_at)
        values ('admin-system-test', 'workflow', now(), now())
        on conflict (worker_id) do update set last_seen_at = now()
        """
    )
    try:
        response = await as_admin.get("/v1/admin/system")
        assert response.status_code == 200
        report = response.json()

        assert report["worker_status"] == "live_idle"
        assert report["live_workers"] >= 1
        assert report["busy_workers"] == 0
        assert report["last_heartbeat"] is not None
        assert report["priced_models"] > 0
        assert any(pin["stage"] == "extract" for pin in report["model_pins"])

        names = {service["name"] for service in report["services"]}
        assert {"OpenRouter", "Bright Data", "Langfuse"} <= names
        # Presence only — a value here would be a credential in an HTTP response.
        for service in report["services"]:
            assert set(service) == {"name", "detail", "configured"}
            assert isinstance(service["configured"], bool)
    finally:
        await db_pool.execute("delete from worker_heartbeats where worker_id = 'admin-system-test'")


async def test_system_distinguishes_busy_and_unavailable_workers(
    as_admin: AsyncClient, db_pool, collab_hunt
) -> None:
    await db_pool.execute("delete from worker_heartbeats")
    job_id = await _job(db_pool, collab_hunt, "running")
    try:
        await db_pool.execute(
            "update jobs set locked_by = 'busy-system-test' where id = $1", job_id
        )
        await db_pool.execute(
            """
            insert into worker_heartbeats (worker_id, mode, started_at, last_seen_at)
            values ('busy-system-test', 'workflow', now(), now())
            """
        )
        busy = (await as_admin.get("/v1/admin/system")).json()
        assert busy["worker_status"] == "live_busy"
        assert busy["busy_workers"] >= 1

        await db_pool.execute(
            "update worker_heartbeats set last_seen_at = now() - interval '2 minutes' "
            "where worker_id = 'busy-system-test'"
        )
        unavailable = (await as_admin.get("/v1/admin/system")).json()
        assert unavailable["worker_status"] == "unavailable"
        assert unavailable["live_workers"] == 0
        # Queue state is separate from worker liveness.
        assert unavailable["running"] >= 1
    finally:
        await db_pool.execute("delete from jobs where id = $1", job_id)
        await db_pool.execute("delete from worker_heartbeats where worker_id = 'busy-system-test'")


# ── the gate ─────────────────────────────────────────────────────────────────


async def test_a_non_admin_is_refused_on_every_operations_route(admin_app, seeded_users) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=admin_app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {seeded_users['member'].token}"},
    ) as client:
        assert (await client.get("/v1/admin/jobs")).status_code == 403
        assert (await client.get("/v1/admin/costs")).status_code == 403
        assert (await client.get("/v1/admin/system")).status_code == 403
        assert (await client.post("/v1/admin/jobs/release-locks")).status_code == 403
