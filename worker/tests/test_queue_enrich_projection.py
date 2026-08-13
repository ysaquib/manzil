"""ENRICH Maps facts survive ingest persist even with no Rubric rows.

After P3-6, ingest takes the `source_results` branch and only writes
`resolved_claims` that are not page-linked. ENRICH dual-writes grocery and
reviews onto both lists so they land through `persist_single_source_claims`
with NULL source_id / hunt_id — the regression when grocery was enabled after
ingest found no Extraction.
"""

from __future__ import annotations

import json
from uuid import uuid4

import asyncpg
from manzil_shared.models import Confidence, FetchOutcome, JobType
from manzil_worker.queue import _persist_ingest_results
from manzil_worker.state import RunState, SourceClaim, SourceResult, SourceState

PLACE_ID = "ChIJmaple"


async def _seed(pool: asyncpg.Pool) -> tuple:  # type: ignore[no-untyped-def]
    hunt_id, property_id, listing_id = uuid4(), uuid4(), uuid4()
    await pool.execute(
        "insert into hunts (id, name, owner_id) values ($1, 'test', $2)", hunt_id, uuid4()
    )
    await pool.execute(
        "insert into properties (id, name, canonical_address) values ($1, 'P', 'addr')",
        property_id,
    )
    await pool.execute(
        "insert into hunt_listings (id, hunt_id, property_id, added_by) values ($1, $2, $3, $4)",
        listing_id,
        hunt_id,
        property_id,
        uuid4(),
    )
    return hunt_id, property_id, listing_id


async def _cleanup(pool: asyncpg.Pool, hunt_id, property_id) -> None:  # type: ignore[no-untyped-def]
    await pool.execute("delete from hunts where id = $1", hunt_id)
    await pool.execute("delete from properties where id = $1", property_id)


def _enrich_claims() -> tuple[SourceClaim, SourceClaim]:
    grocery = SourceClaim(
        criterion_key="grocery_proximity",
        value=7.5,
        confidence=Confidence.HIGH,
        evidence_quote="Nearest grocery: Kroger — 7.5 min driving (Google Maps)",
        origin_key="google_maps:grocery",
        source_id=None,
        model="maps",
        prompt_version=0,
        resolution_rule="single_source",
    )
    reviews = SourceClaim(
        criterion_key="management_reviews",
        value={"rating": 4.2, "summary": "Responsive management."},
        confidence=Confidence.HIGH,
        evidence_quote="Google Places rating 4.2 (87 ratings)",
        origin_key=f"google_places:{PLACE_ID}",
        source_id=None,
        model="maps",
        prompt_version=0,
        resolution_rule="single_source",
    )
    return grocery, reviews


def _base_state(url: str) -> RunState:
    state = RunState(job_id=uuid4(), job_type=JobType.INGEST, url=url)
    state.sources = [
        SourceState(
            url=url, tier_used=1, outcome=FetchOutcome.SUCCESS, cleaned_text="x", cleaned_hash="h"
        )
    ]
    return state


async def _run(pool: asyncpg.Pool, listing_id, property_id, state: RunState) -> None:  # type: ignore[no-untyped-def]
    async with pool.acquire() as conn, conn.transaction():
        await _persist_ingest_results(
            conn,
            hunt_listing_id=listing_id,
            property_id=property_id,
            rubric_version=1,
            state=state,
        )


async def test_source_results_branch_persists_enrich_without_rubric(
    pg_pool: asyncpg.Pool,
) -> None:
    """The live post-P3-6 path: source_results populated, no rubric_criteria."""
    hunt_id, property_id, listing_id = await _seed(pg_pool)
    try:
        rubric_count = await pg_pool.fetchval(
            "select count(*) from rubric_criteria where hunt_id = $1", hunt_id
        )
        assert rubric_count == 0

        url = f"https://x.test/{uuid4()}"
        grocery, reviews = _enrich_claims()
        state = _base_state(url)
        state.source_results = [
            SourceResult(
                source_url=url,
                syndication_family="independent",
                role="submitted",
                source_claims=[],
            )
        ]
        state.source_claims = [grocery, reviews]
        state.resolved_claims = [grocery.model_copy(deep=True), reviews.model_copy(deep=True)]
        await _run(pg_pool, listing_id, property_id, state)

        rows = await pg_pool.fetch(
            """
            select criterion_key, value, source_id, hunt_id, origin_key, resolution_rule
            from current_extractions
            where property_id = $1
              and criterion_key in ('grocery_proximity', 'management_reviews')
            order by criterion_key
            """,
            property_id,
        )
        by_key = {row["criterion_key"]: row for row in rows}
        assert set(by_key) == {"grocery_proximity", "management_reviews"}

        grocery_row = by_key["grocery_proximity"]
        assert json.loads(grocery_row["value"]) == 7.5
        assert grocery_row["source_id"] is None
        assert grocery_row["hunt_id"] is None
        assert grocery_row["origin_key"] == "google_maps:grocery"
        assert grocery_row["resolution_rule"] == "single_source"

        reviews_row = by_key["management_reviews"]
        assert json.loads(reviews_row["value"]) == {
            "rating": 4.2,
            "summary": "Responsive management.",
        }
        assert reviews_row["source_id"] is None
        assert reviews_row["hunt_id"] is None
        assert reviews_row["origin_key"] == f"google_places:{PLACE_ID}"
        assert reviews_row["resolution_rule"] == "single_source"
    finally:
        await _cleanup(pg_pool, hunt_id, property_id)


async def test_legacy_branch_dual_write_does_not_double_persist(
    pg_pool: asyncpg.Pool,
) -> None:
    """No source_results: persist reads source_claims only — one current row each."""
    hunt_id, property_id, listing_id = await _seed(pg_pool)
    try:
        url = f"https://x.test/{uuid4()}"
        grocery, reviews = _enrich_claims()
        state = _base_state(url)
        # Dual-write as ENRICH does; legacy branch must not write both lists.
        state.source_claims = [grocery, reviews]
        state.resolved_claims = [grocery.model_copy(deep=True), reviews.model_copy(deep=True)]
        await _run(pg_pool, listing_id, property_id, state)

        for key, origin in (
            ("grocery_proximity", "google_maps:grocery"),
            ("management_reviews", f"google_places:{PLACE_ID}"),
        ):
            current = await pg_pool.fetchval(
                "select count(*) from current_extractions "
                "where property_id = $1 and criterion_key = $2",
                property_id,
                key,
            )
            assert current == 1
            # candidate + resolved, not four rows from dual-write.
            total = await pg_pool.fetchval(
                "select count(*) from extractions where property_id = $1 and criterion_key = $2",
                property_id,
                key,
            )
            assert total == 2
            assert (
                await pg_pool.fetchval(
                    "select origin_key from current_extractions "
                    "where property_id = $1 and criterion_key = $2",
                    property_id,
                    key,
                )
                == origin
            )
    finally:
        await _cleanup(pg_pool, hunt_id, property_id)
