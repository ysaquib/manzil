"""End-to-end cached-evidence backfill for an extracted Maps Criterion."""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import asyncpg
from manzil_shared.models import JobType
from manzil_worker.llm.tools import AgentResult
from manzil_worker.queue import make_class_refresh_dispatcher, run_worker_loop


async def test_maps_backfill_reuses_geocode_persists_hunt_truth_and_rescores(
    pg_pool: asyncpg.Pool,
) -> None:
    hunt_id, property_id, source_id, listing_id, job_id = (uuid4() for _ in range(5))
    owner_id = uuid4()
    custom_key = f"custom:{uuid4()}"
    source_url = f"https://example.test/listing/{uuid4()}"
    calls: list[dict] = []

    async def maps_agent(stage, task, tools, max_turns):  # type: ignore[no-untyped-def]
        assert stage == "custom_match_location"
        assert max_turns == 8
        payload = json.loads(task)
        calls.append(payload)
        assert payload["property"] == {
            "lat": 42.3314,
            "lng": -83.0458,
            "address": "123 Woodward Ave, Detroit, MI",
        }
        assert {tool.__name__ for tool in tools} == {"geocode", "places_nearby", "commute_time"}
        return AgentResult(
            final_text=json.dumps(
                {
                    "value": True,
                    "confidence": "high",
                    "evidence": "Cached origin is within the requested commute bound.",
                }
            ),
            turns=1,
        )

    try:
        await pg_pool.execute(
            """
            insert into hunts (id, name, owner_id, rubric_version)
            values ($1, 'Maps custom backfill', $2, 1)
            """,
            hunt_id,
            owner_id,
        )
        await pg_pool.execute(
            """
            insert into rubric_criteria (
                hunt_id, custom_def, options, unknown_delta, is_bonus, position
            ) values ($1, $2::jsonb, $3::jsonb, 0, true, 0)
            """,
            hunt_id,
            json.dumps(
                {
                    "schema_version": 1,
                    "key": custom_key,
                    "label": "Short commute",
                    "description": "Whether downtown is within 20 minutes.",
                    "fact_scope": "property",
                    "value_schema": {"type": "boolean"},
                    "requires_tool": "maps",
                    "refresh_class": "location",
                    "routing_confirmed": True,
                }
            ),
            json.dumps([{"match": {"op": "bool", "value": True}, "delta": 1}]),
        )
        await pg_pool.execute(
            """
            insert into properties (
                id, name, canonical_address, place_id, lat, lng, city, state, county
            ) values (
                $1, 'Woodward Place', '123 Woodward Ave, Detroit, MI',
                'cached-place', 42.3314, -83.0458, 'Detroit', 'MI', 'Wayne County'
            )
            """,
            property_id,
        )
        await pg_pool.execute(
            """
            insert into property_sources (
                id, property_id, url, site_domain, cleaned_text, cleaned_text_hash,
                last_fetched_at, last_success_at
            ) values (
                $1, $2, $3, 'example.test', 'cached listing text', 'cached-hash', now(), now()
            )
            """,
            source_id,
            property_id,
            source_url,
        )
        await pg_pool.execute(
            """
            insert into hunt_listings (
                id, hunt_id, property_id, added_by, submitted_source_id, source_policy
            ) values ($1, $2, $3, $4, $5, 'trust_link')
            """,
            listing_id,
            hunt_id,
            property_id,
            owner_id,
            source_id,
        )
        floor_plan_id = await pg_pool.fetchval(
            """
            insert into floor_plans (
                property_id, source_id, plan_name, beds, baths, rent_min, rent_max
            ) values ($1, $2, 'A1', 1, 1, 1500, 1500)
            returning id
            """,
            property_id,
            source_id,
        )
        await pg_pool.execute(
            """
            insert into jobs (
                id, hunt_id, hunt_listing_id, type, state, requested_by, payload
            ) values ($1, $2, $3, 'refresh', 'queued', $4, $5::jsonb)
            """,
            job_id,
            hunt_id,
            listing_id,
            owner_id,
            json.dumps(
                {
                    "url": source_url,
                    "hunt_id": str(hunt_id),
                    "listing_id": str(listing_id),
                    "scope": "custom_match",
                    "custom_criterion_keys": [custom_key],
                    "trigger": "rubric:custom-backfill",
                }
            ),
        )

        dispatch = {
            JobType.REFRESH: make_class_refresh_dispatcher(
                dsn=None,
                fetchers_factory=dict,
                call_agent=maps_agent,
            )
        }
        await run_worker_loop(pg_pool, asyncio.Event(), dispatch=dispatch, until_empty=True)

        job = await pg_pool.fetchrow("select state, plan from jobs where id=$1", job_id)
        plan = json.loads(job["plan"]) if isinstance(job["plan"], str) else job["plan"]
        assert job["state"] == "done"
        # Refresh SCORE is persistence-backed after projection, not a RunState stage.
        assert plan["stages"] == ["PLAN", "CUSTOM_MATCH"]
        assert calls and len(calls) == 1
        assert not await pg_pool.fetchval(
            "select exists(select 1 from job_events where job_id=$1 and stage='FETCH')", job_id
        )

        extraction = await pg_pool.fetchrow(
            """
            select hunt_id, source_id, value, confidence, resolution_rule
            from current_extractions
            where property_id=$1 and hunt_id=$2 and criterion_key=$3
            """,
            property_id,
            hunt_id,
            custom_key,
        )
        assert extraction is not None
        assert extraction["hunt_id"] == hunt_id
        assert extraction["source_id"] is None
        assert json.loads(extraction["value"]) is True
        assert extraction["confidence"] == "high"
        assert extraction["resolution_rule"] == "custom_match_maps"

        breakdown_raw = await pg_pool.fetchval(
            "select breakdown from scores where hunt_listing_id=$1 and floor_plan_id=$2",
            listing_id,
            floor_plan_id,
        )
        breakdown = json.loads(breakdown_raw)
        criterion = next(row for row in breakdown["criteria"] if row["key"] == custom_key)
        assert criterion["value"] is True
        assert criterion["delta"] == 1
    finally:
        await pg_pool.execute("delete from hunts where id=$1", hunt_id)
        await pg_pool.execute("delete from properties where id=$1", property_id)
