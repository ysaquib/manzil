"""P1-3: the in-process worker loop, driven through the real FastAPI lifespan.

With MANZIL_WORKER_INPROCESS=true the lifespan starts the durable-queue loop as
a background task. This test proves an end-to-end ingest job is claimed and run
to `done` while `/v1/health` still serves, and that lifespan shutdown drains
cleanly. Fetchers are swapped for a committed fixture page and the LLM seam runs
in replay, so no network or tokens are touched. Skips without a database.
"""

from __future__ import annotations

import asyncio
import json
import os
from uuid import uuid4

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient
from manzil_worker.fetching.results import FetchResult
from manzil_worker.phase0_rubric import phase0_rubric

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
)
FIXTURE_URL = "https://maple-court.seed.example/floorplans"
PAGE = "e2e_listing.html"
SETTINGS = {
    "default_source_policy": "tiers_1_2_3",
    "cost_estimate_mode": "conservative",
    "min_confidence": "medium",
    "proximity_mode": "driving",
}


class _FixtureFetcher:
    tier = 1

    def __init__(self, body: str) -> None:
        self._body = body

    async def fetch(self, url: str, *, capture_screenshot: bool = False) -> FetchResult:
        return FetchResult(url=url, final_url=url, status_code=200, body=self._body, tier=1)


async def _seed_one_ingest_job(pool: asyncpg.Pool, hunt_id, listing_id) -> None:  # type: ignore[no-untyped-def]
    user_id, prop_id = uuid4(), uuid4()
    await pool.execute(
        "insert into hunts (id, name, owner_id, settings) values ($1, 'inproc', $2, $3::jsonb)",
        hunt_id,
        user_id,
        json.dumps(SETTINGS),
    )
    for crit in phase0_rubric():
        await pool.execute(
            """
            insert into rubric_criteria
                (hunt_id, catalog_key, options, unknown_delta, non_negotiable, is_bonus, position)
            values ($1, $2, $3::jsonb, $4, $5::jsonb, $6, $7)
            """,
            hunt_id,
            crit.catalog_key,
            json.dumps([o.model_dump(mode="json") for o in crit.options]),
            crit.unknown_delta,
            json.dumps(crit.non_negotiable.model_dump(mode="json"))
            if crit.non_negotiable
            else None,
            crit.is_bonus,
            crit.position,
        )
    await pool.execute(
        "insert into properties (id, name, canonical_address) values ($1, 'Maple', 'x')", prop_id
    )
    await pool.execute(
        "insert into hunt_listings (id, hunt_id, property_id, added_by) values ($1, $2, $3, $4)",
        listing_id,
        hunt_id,
        prop_id,
        user_id,
    )
    await pool.execute(
        "insert into jobs (hunt_listing_id, type, state, payload) "
        "values ($1, 'ingest', 'queued', $2::jsonb)",
        listing_id,
        json.dumps({"url": FIXTURE_URL}),
    )


async def test_inprocess_loop_processes_a_job_while_serving_and_drains(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, timeout=5, min_size=1, max_size=4)
    except (OSError, asyncpg.PostgresError) as exc:  # pragma: no cover - env guard
        pytest.skip(f"Postgres unreachable at {DATABASE_URL}: {exc}")

    from pathlib import Path

    import manzil_worker.queue as queue_mod
    from manzil_api.config import get_settings
    from manzil_api.main import create_app, lifespan

    body = (
        Path(__file__).resolve().parents[2] / "worker" / "tests" / "fixtures" / "pages" / PAGE
    ).read_text()
    monkeypatch.setenv("MANZIL_WORKER_INPROCESS", "true")
    monkeypatch.setenv("MANZIL_LLM_MODE", "replay")
    monkeypatch.setattr(queue_mod, "_default_fetchers", lambda: {1: _FixtureFetcher(body)})
    get_settings.cache_clear()

    hunt_id, listing_id = uuid4(), uuid4()
    try:
        await _seed_one_ingest_job(pool, hunt_id, listing_id)

        app = create_app()
        async with lifespan(app):  # starts the in-process worker task
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                health = await client.get("/v1/health")
                assert health.status_code == 200  # API serves while the loop runs

                async def job_state() -> str:
                    return await pool.fetchval(
                        "select state from jobs where hunt_listing_id = $1", listing_id
                    )

                for _ in range(100):  # up to ~10s
                    if await job_state() in ("done", "failed"):
                        break
                    await asyncio.sleep(0.1)
                assert await job_state() == "done"
        # lifespan exited => clean-shutdown drain completed without hanging.

        total = await pool.fetchval(
            "select total from scores s join hunt_listings hl on hl.id = s.hunt_listing_id "
            "where hl.hunt_id = $1",
            hunt_id,
        )
        assert total is not None and total != 0
    finally:
        await pool.execute("delete from hunts where id = $1", hunt_id)
        await pool.close()
        get_settings.cache_clear()  # don't leak worker_inprocess=true to other tests
