"""P3-5 policy-relaxation DISCOVER refresh through the durable queue."""

from __future__ import annotations

import asyncio
import json
import os
from uuid import uuid4

import asyncpg
import pytest
from manzil_shared.models import JobType
from manzil_worker.llm.tools import AgentResult
from manzil_worker.queue import make_discover_refresh_dispatcher, run_worker_loop

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
)


async def _pool_or_skip() -> asyncpg.Pool:
    try:
        return await asyncpg.create_pool(DATABASE_URL, timeout=5, min_size=1, max_size=4)
    except (OSError, asyncpg.PostgresError) as exc:  # pragma: no cover
        pytest.skip(f"Postgres unreachable at {DATABASE_URL}: {exc}")


async def _discover(stage, task, tools, max_turns):  # type: ignore[no-untyped-def]
    return AgentResult(
        final_text=json.dumps(
            {
                "official_url": "https://maple-court.example/",
                "official_confidence": "high",
                "official_evidence": "same name and address",
                "candidates": [
                    {
                        "url": "https://rent.com/maple-court",
                        "same_property": True,
                        "confidence": "high",
                        "evidence": "same name and address",
                    }
                ],
            }
        ),
        turns=1,
    )


async def test_discover_refresh_persists_link_only_sources_and_assurance() -> None:
    pool = await _pool_or_skip()
    hunt_id, listing_id, property_id, job_id = uuid4(), uuid4(), uuid4(), uuid4()
    submitted = f"https://apartments.com/maple-court/{uuid4()}"
    try:
        await pool.execute(
            "insert into hunts (id, name, owner_id) values ($1, 'DiscoverRefresh', $2)",
            hunt_id,
            uuid4(),
        )
        await pool.execute(
            """insert into properties (id, name, canonical_address)
               values ($1, 'Maple Court', '120 Maple Court Dr, Detroit, MI')""",
            property_id,
        )
        await pool.execute(
            """insert into hunt_listings
                   (id, hunt_id, property_id, added_by, source_policy, single_source_reason)
               values ($1, $2, $3, $4, 'tiers_1_2_3', 'trust_link')""",
            listing_id,
            hunt_id,
            property_id,
            uuid4(),
        )
        await pool.execute(
            """insert into property_sources (property_id, url, site_domain, last_fetched_at)
               values ($1, $2, 'apartments.com', now())""",
            property_id,
            submitted,
        )
        await pool.execute(
            """insert into jobs (id, hunt_id, hunt_listing_id, type, state, payload)
               values ($1, $2, $3, 'refresh', 'queued', $4::jsonb)""",
            job_id,
            hunt_id,
            listing_id,
            json.dumps(
                {
                    "hunt_id": str(hunt_id),
                    "listing_id": str(listing_id),
                    "url": submitted,
                    "scope": "discover",
                    "source_policy": "tiers_1_2_3",
                }
            ),
        )

        dispatch = {
            JobType.REFRESH: make_discover_refresh_dispatcher(
                dsn=None,
                fetchers_factory=lambda: {1: object(), 2: object(), 3: object()},  # type: ignore[dict-item]
                call_agent=_discover,
            )
        }
        await run_worker_loop(pool, asyncio.Event(), dispatch=dispatch, until_empty=True)

        job = await pool.fetchrow(
            "select state, plan, cost_actual_usd from jobs where id = $1", job_id
        )
        assert job is not None and job["state"] == "done"
        plan = json.loads(job["plan"]) if isinstance(job["plan"], str) else job["plan"]
        assert plan["stages"] == ["DISCOVER"]
        assert plan["trigger"] == "user:source_policy"
        rows = await pool.fetch(
            """select url, is_official, last_fetched_at from property_sources
               where property_id = $1 order by url""",
            property_id,
        )
        discovered = {row["url"]: row for row in rows if row["url"] != submitted}
        assert set(discovered) == {
            "https://maple-court.example/",
            "https://rent.com/maple-court",
        }
        assert discovered["https://maple-court.example/"]["is_official"] is True
        assert all(row["last_fetched_at"] is None for row in discovered.values())
        official, reason = await pool.fetchrow(
            """select p.official_url, hl.single_source_reason
               from properties p join hunt_listings hl on hl.property_id = p.id
               where hl.id = $1""",
            listing_id,
        )
        assert official == "https://maple-court.example/"
        assert reason is None
    finally:
        await pool.execute("delete from hunts where id = $1", hunt_id)
        await pool.execute("delete from properties where id = $1", property_id)
        await pool.close()
