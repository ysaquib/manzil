"""P3-9 persistence: the mandatory-fees/heating blocks project onto fee slots
and append-only extractions, the display composition lands on
hunt_listings.all_in_components, and rescore recomposes the same §9.5 figure
from the persisted rows (mode flip → different total, zero refetch)."""

from __future__ import annotations

import json
from uuid import uuid4

import asyncpg
from manzil_shared.models import (
    Confidence,
    FetchOutcome,
    JobType,
    MatchOp,
    OptionMatch,
    RubricCriterion,
    RubricOption,
)
from manzil_worker.queue import _persist_ingest_results
from manzil_worker.stages.rescore import rescore_hunt
from manzil_worker.state import (
    FloorPlanIn,
    HeatingIn,
    MandatoryFeeIn,
    MandatoryFeesIn,
    PlanScore,
    RunState,
    SourceState,
)

AMOUNTS = {
    "electric": (120.0, 80.0),
    "electric_heat": (220.0, 140.0),
    "gas_heat": (150.0, 90.0),
    "water": (55.0, 40.0),
    "sewer": (45.0, 35.0),
    "trash": (30.0, 25.0),
}


async def _seed(pool: asyncpg.Pool, *, metro: str) -> tuple:  # type: ignore[no-untyped-def]
    hunt_id, property_id, listing_id = uuid4(), uuid4(), uuid4()
    await pool.execute(
        "insert into hunts (id, name, owner_id, rubric_version) values ($1, 'test', $2, 1)",
        hunt_id,
        uuid4(),
    )
    await pool.execute(
        "insert into properties (id, name, canonical_address, city) values ($1, 'P', '1 Main', $2)",
        property_id,
        metro,
    )
    await pool.execute(
        "insert into hunt_listings (id, hunt_id, property_id, added_by) values ($1, $2, $3, $4)",
        listing_id,
        hunt_id,
        property_id,
        uuid4(),
    )
    for utility, (high, median) in AMOUNTS.items():
        await pool.execute(
            """
            insert into utility_baselines
                (metro, beds_bucket, utility, monthly_high, monthly_median)
            values ($1, 2, $2, $3, $4)
            """,
            metro,
            utility,
            high,
            median,
        )
    return hunt_id, property_id, listing_id


async def _cleanup(pool: asyncpg.Pool, hunt_id, property_id, metro) -> None:  # type: ignore[no-untyped-def]
    await pool.execute("delete from hunts where id = $1", hunt_id)
    await pool.execute("delete from properties where id = $1", property_id)
    await pool.execute("delete from utility_baselines where metro = $1", metro)


def _state() -> RunState:
    url = f"https://x.test/{uuid4()}"
    state = RunState(job_id=uuid4(), job_type=JobType.INGEST, url=url)
    state.sources = [
        SourceState(
            url=url, tier_used=1, outcome=FetchOutcome.SUCCESS, cleaned_text="x", cleaned_hash="h"
        )
    ]
    state.mandatory_fees = MandatoryFeesIn(
        fees=[
            MandatoryFeeIn(name="valet trash", amount_monthly=25.0),
            MandatoryFeeIn(name="amenity fee", amount_monthly=10.0),  # no standard slot
        ],
        evidence_quote="Valet trash $25/mo; amenity fee $10/mo",
    )
    state.heating = HeatingIn(heating="gas", evidence_quote="gas forced-air heat")
    state.floor_plans = [FloorPlanIn(plan_name="2x2", beds=2, baths=2.0, rent_max=1500.0)]
    state.scores = [
        PlanScore(
            plan_name="2x2",
            breakdown={"total": 9.0},
            all_in_components={
                "total": 1905.0,
                "estimated_total": 370.0,
                "components": [{"name": "rent", "amount": 1500.0, "tag": "actual"}],
                "badges": [],
                "mode": "conservative",
            },
        )
    ]
    state.display_score_index = 0
    state.all_in_components = {
        "total": 1905.0,
        "estimated_total": 370.0,
        "components": [],
        "badges": [],
        "mode": "conservative",
    }
    return state


async def test_projection_persists_p39_blocks_and_composition(pg_pool: asyncpg.Pool) -> None:
    metro = f"ProjVille-{uuid4().hex[:6]}"
    hunt_id, property_id, listing_id = await _seed(pg_pool, metro=metro)
    try:
        state = _state()
        async with pg_pool.acquire() as conn, conn.transaction():
            await _persist_ingest_results(
                conn,
                hunt_listing_id=listing_id,
                property_id=property_id,
                rubric_version=1,
                state=state,
            )
        slot = await pg_pool.fetchrow(
            "select amount, value_state from fee_checklist "
            "where hunt_listing_id = $1 and fee_slot = 'valet_trash'",
            listing_id,
        )
        assert slot is not None and float(slot["amount"]) == 25.0
        assert slot["value_state"] == "extracted"
        fees_row = await pg_pool.fetchval(
            "select value from extractions where property_id = $1 "
            "and criterion_key = 'mandatory_fees'",
            property_id,
        )
        names = {f["name"] for f in json.loads(fees_row)}
        assert names == {"valet trash", "amenity fee"}
        heating_row = await pg_pool.fetchval(
            "select value from extractions where property_id = $1 "
            "and criterion_key = 'heating_type'",
            property_id,
        )
        assert json.loads(heating_row) == "gas"
        stored = await pg_pool.fetchval(
            "select all_in_components from hunt_listings where id = $1", listing_id
        )
        assert json.loads(stored)["total"] == 1905.0
        # P3-9 follow-up: the plan's own composition lands on its scores row.
        per_plan = await pg_pool.fetchval(
            "select all_in_components from scores where hunt_listing_id = $1", listing_id
        )
        assert json.loads(per_plan)["components"][0]["amount"] == 1500.0
    finally:
        await _cleanup(pg_pool, hunt_id, property_id, metro)


async def test_rescore_recomposes_and_mode_flip_changes_total(pg_pool: asyncpg.Pool) -> None:
    metro = f"RescoreVille-{uuid4().hex[:6]}"
    hunt_id, property_id, listing_id = await _seed(pg_pool, metro=metro)
    rubric = [
        RubricCriterion(
            hunt_id=hunt_id,
            catalog_key="all_in_monthly",
            options=[
                RubricOption(match=OptionMatch(op=MatchOp.LT, value=2500), delta=0.5),
            ],
            unknown_delta=-1.0,
            position=0,
        )
    ]
    try:
        # Persist the P3-9 blocks through the real projection first.
        async with pg_pool.acquire() as conn, conn.transaction():
            await _persist_ingest_results(
                conn,
                hunt_listing_id=listing_id,
                property_id=property_id,
                rubric_version=1,
                state=_state(),
            )
        # utilities_included never extracted (page silent) → estimate-all branch.
        async with pg_pool.acquire() as conn, conn.transaction():
            await rescore_hunt(
                conn,
                hunt_id=hunt_id,
                rubric=rubric,
                rubric_version=2,
                min_confidence=Confidence.MEDIUM,
            )
        breakdown = await pg_pool.fetchval(
            "select breakdown from scores where hunt_listing_id = $1", listing_id
        )
        entry = next(
            c for c in json.loads(breakdown)["criteria"] if c["key"] == "all_in_monthly"
        )
        # rent 1500 + valet trash 25 + amenity 10 + electric 120 + gas_heat 150
        # + water 55 + sewer 45 (trash estimate suppressed by billed fee) = 1905
        assert entry["value"] == 1905.0
        stored = json.loads(
            await pg_pool.fetchval(
                "select all_in_components from hunt_listings where id = $1", listing_id
            )
        )
        assert stored["total"] == 1905.0
        assert "fees_unverified" in stored["badges"]  # page silent on inclusions
        # P3-9 follow-up: rescore writes the recomposed detail per scores row too.
        per_plan = json.loads(
            await pg_pool.fetchval(
                "select all_in_components from scores where hunt_listing_id = $1", listing_id
            )
        )
        assert per_plan["total"] == 1905.0
        rent_line = next(c for c in per_plan["components"] if c["name"] == "rent")
        assert rent_line["amount"] == 1500.0

        # Mode flip conservative → median rescores without any refetch (§9.5).
        async with pg_pool.acquire() as conn, conn.transaction():
            await rescore_hunt(
                conn,
                hunt_id=hunt_id,
                rubric=rubric,
                rubric_version=3,
                min_confidence=Confidence.MEDIUM,
                cost_estimate_mode="median",
            )
        breakdown = await pg_pool.fetchval(
            "select breakdown from scores where hunt_listing_id = $1", listing_id
        )
        entry = next(
            c for c in json.loads(breakdown)["criteria"] if c["key"] == "all_in_monthly"
        )
        # 1500 + 35 fees + (80 + 90 + 40 + 35) median estimates = 1780
        assert entry["value"] == 1780.0
    finally:
        await _cleanup(pg_pool, hunt_id, property_id, metro)
