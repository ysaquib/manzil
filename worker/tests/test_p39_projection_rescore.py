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
    OneTimeFeeIn,
    OneTimeFeesIn,
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


async def _seed(pool: asyncpg.Pool, *, city: str, state: str = "MI") -> tuple:  # type: ignore[no-untyped-def]
    hunt_id, property_id, listing_id = uuid4(), uuid4(), uuid4()
    await pool.execute(
        "insert into hunts (id, name, owner_id, rubric_version) values ($1, 'test', $2, 1)",
        hunt_id,
        uuid4(),
    )
    await pool.execute(
        """
        insert into properties (id, name, canonical_address, city, state)
        values ($1, 'P', '1 Main', $2, $3)
        """,
        property_id,
        city,
        state,
    )
    await pool.execute(
        "insert into hunt_listings (id, hunt_id, property_id, added_by) values ($1, $2, $3, $4)",
        listing_id,
        hunt_id,
        property_id,
        uuid4(),
    )
    region = ("city", state, city)
    for utility, (high, median) in AMOUNTS.items():
        await pool.execute(
            """
            insert into utility_baselines
                (geo_level, state, region_name, beds_bucket, utility,
                 monthly_high, monthly_median)
            values ($1, $2, $3, 2, $4, $5, $6)
            """,
            *region,
            utility,
            high,
            median,
        )
    return hunt_id, property_id, listing_id


async def _cleanup(pool: asyncpg.Pool, hunt_id, property_id, city, state="MI") -> None:  # type: ignore[no-untyped-def]
    await pool.execute("delete from hunts where id = $1", hunt_id)
    await pool.execute("delete from properties where id = $1", property_id)
    await pool.execute(
        """
        delete from utility_baselines
        where geo_level = 'city' and state = $1 and region_name = $2
        """,
        state,
        city,
    )


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
    state.one_time_fees = OneTimeFeesIn(
        fees=[
            OneTimeFeeIn(name="application fee", amount=50.0, basis="per_person"),
            OneTimeFeeIn(name="pet deposit", amount=300.0, basis="per_pet", refundable=True),
            OneTimeFeeIn(name="elevator reservation", amount=75.0),  # no standard slot
        ],
        evidence_quote="App fee $50/applicant; $300 refundable pet deposit",
    )
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
    hunt_id, property_id, listing_id = await _seed(pg_pool, city=metro)
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
        # One-time fees (§20 2026-07-18): extraction row + move-in slots; a fee
        # with no standard slot still persists via the extraction.
        one_time_row = await pg_pool.fetchval(
            "select value from extractions where property_id = $1 "
            "and criterion_key = 'one_time_fees'",
            property_id,
        )
        one_time = json.loads(one_time_row)
        assert [(f["name"], f["amount"], f["basis"]) for f in one_time] == [
            ("application fee", 50.0, "per_person"),
            ("pet deposit", 300.0, "per_pet"),
            ("elevator reservation", 75.0, "flat"),
        ]
        assert one_time[1]["refundable"] is True
        app_slot = await pg_pool.fetchrow(
            "select amount, value_state from fee_checklist "
            "where hunt_listing_id = $1 and fee_slot = 'application_fee'",
            listing_id,
        )
        assert app_slot is not None and float(app_slot["amount"]) == 50.0
        assert app_slot["value_state"] == "extracted"
        deposit_slot = await pg_pool.fetchval(
            "select amount from fee_checklist "
            "where hunt_listing_id = $1 and fee_slot = 'pet_deposit'",
            listing_id,
        )
        assert float(deposit_slot) == 300.0
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
    hunt_id, property_id, listing_id = await _seed(pg_pool, city=metro)
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
        entry = next(c for c in json.loads(breakdown)["criteria"] if c["key"] == "all_in_monthly")
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

        # An all_in_monthly override beats the composition (§9.6): the scored
        # value is the human's figure and the display plan is marked overridden.
        await pg_pool.execute(
            "insert into overrides "
            "(hunt_listing_id, criterion_key, target_scope, value, user_id) "
            "values ($1, 'all_in_monthly', 'property', '1800'::jsonb, $2)",
            listing_id,
            uuid4(),
        )
        async with pg_pool.acquire() as conn, conn.transaction():
            await rescore_hunt(
                conn,
                hunt_id=hunt_id,
                rubric=rubric,
                rubric_version=2,
                min_confidence=Confidence.MEDIUM,
            )
        overridden = json.loads(
            await pg_pool.fetchval(
                "select all_in_components from scores where hunt_listing_id = $1", listing_id
            )
        )
        assert overridden["total"] == 1800.0 and overridden["overridden"] is True
        entry = next(
            c
            for c in json.loads(
                await pg_pool.fetchval(
                    "select breakdown from scores where hunt_listing_id = $1", listing_id
                )
            )["criteria"]
            if c["key"] == "all_in_monthly"
        )
        assert entry["value"] == 1800

        # Appending a null override is the revert tombstone (§9.6, append-only):
        # the composition's own figure returns and the overridden mark drops.
        await pg_pool.execute(
            "insert into overrides "
            "(hunt_listing_id, criterion_key, target_scope, value, user_id) "
            "values ($1, 'all_in_monthly', 'property', 'null'::jsonb, $2)",
            listing_id,
            uuid4(),
        )
        async with pg_pool.acquire() as conn, conn.transaction():
            await rescore_hunt(
                conn,
                hunt_id=hunt_id,
                rubric=rubric,
                rubric_version=2,
                min_confidence=Confidence.MEDIUM,
            )
        reverted = json.loads(
            await pg_pool.fetchval(
                "select all_in_components from scores where hunt_listing_id = $1", listing_id
            )
        )
        assert reverted["total"] == 1905.0
        assert "overridden" not in reverted

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
        entry = next(c for c in json.loads(breakdown)["criteria"] if c["key"] == "all_in_monthly")
        # 1500 + 35 fees + (80 + 90 + 40 + 35) median estimates = 1780
        assert entry["value"] == 1780.0
    finally:
        await _cleanup(pg_pool, hunt_id, property_id, metro)


async def test_rescore_applies_and_reverts_individual_utility_corrections(
    pg_pool: asyncpg.Pool,
) -> None:
    metro = f"UtilityOverrideVille-{uuid4().hex[:6]}"
    hunt_id, property_id, listing_id = await _seed(pg_pool, city=metro)
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
        async with pg_pool.acquire() as conn, conn.transaction():
            await _persist_ingest_results(
                conn,
                hunt_listing_id=listing_id,
                property_id=property_id,
                rubric_version=1,
                state=_state(),
            )
        # A combined extracted water/sewer charge must yield to a manual
        # per-utility correction instead of appearing alongside it.
        await pg_pool.execute(
            """
            insert into fee_checklist
                (hunt_listing_id, fee_slot, amount, value_state)
            values ($1, 'water_sewer', 60, 'extracted')
            """,
            listing_id,
        )
        await pg_pool.executemany(
            """
            insert into utility_overrides
                (hunt_listing_id, utility, included, monthly_amount, user_id)
            values ($1, $2, $3, $4, $5)
            """,
            [
                (listing_id, "water", True, None, uuid4()),
                (listing_id, "electric", False, 92, uuid4()),
            ],
        )
        async with pg_pool.acquire() as conn, conn.transaction():
            await rescore_hunt(
                conn,
                hunt_id=hunt_id,
                rubric=rubric,
                rubric_version=2,
                min_confidence=Confidence.MEDIUM,
            )
        corrected = json.loads(
            await pg_pool.fetchval(
                "select all_in_components from hunt_listings where id = $1",
                listing_id,
            )
        )
        assert corrected["total"] == 1822.0
        assert not any(component["name"] == "water_sewer" for component in corrected["components"])
        electric = next(
            component for component in corrected["components"] if component["name"] == "electric"
        )
        assert electric["amount"] == 92.0 and electric["tag"] == "actual"

        # Reverting both utilities restores the extracted combined charge and
        # the baseline electric figure without touching either history.
        await pg_pool.executemany(
            """
            insert into utility_overrides
                (hunt_listing_id, utility, included, monthly_amount, user_id)
            values ($1, $2, null, null, $3)
            """,
            [
                (listing_id, "water", uuid4()),
                (listing_id, "electric", uuid4()),
            ],
        )
        async with pg_pool.acquire() as conn, conn.transaction():
            await rescore_hunt(
                conn,
                hunt_id=hunt_id,
                rubric=rubric,
                rubric_version=3,
                min_confidence=Confidence.MEDIUM,
            )
        reverted = json.loads(
            await pg_pool.fetchval(
                "select all_in_components from hunt_listings where id = $1",
                listing_id,
            )
        )
        assert reverted["total"] == 1865.0
        assert any(component["name"] == "water_sewer" for component in reverted["components"])
        assert (
            await pg_pool.fetchval(
                "select count(*) from utility_overrides where hunt_listing_id = $1",
                listing_id,
            )
            == 4
        )
    finally:
        await _cleanup(pg_pool, hunt_id, property_id, metro)


async def test_rescore_uses_manual_unmapped_mandatory_fee_slots(pg_pool: asyncpg.Pool) -> None:
    metro = f"CustomFeeVille-{uuid4().hex[:6]}"
    hunt_id, property_id, listing_id = await _seed(pg_pool, city=metro)
    rubric = [
        RubricCriterion(
            hunt_id=hunt_id,
            catalog_key="all_in_monthly",
            options=[RubricOption(match=OptionMatch(op=MatchOp.LT, value=2500), delta=0.5)],
            unknown_delta=-1.0,
            position=0,
        )
    ]
    try:
        async with pg_pool.acquire() as conn, conn.transaction():
            await _persist_ingest_results(
                conn,
                hunt_listing_id=listing_id,
                property_id=property_id,
                rubric_version=1,
                state=_state(),
            )
        await pg_pool.execute(
            """
            insert into fee_checklist
                (hunt_listing_id, fee_slot, amount, value_state, entered_by)
            values ($1, 'amenity fee', 18, 'manual', $2)
            """,
            listing_id,
            uuid4(),
        )
        async with pg_pool.acquire() as conn, conn.transaction():
            await rescore_hunt(
                conn,
                hunt_id=hunt_id,
                rubric=rubric,
                rubric_version=2,
                min_confidence=Confidence.MEDIUM,
            )
        corrected = json.loads(
            await pg_pool.fetchval(
                "select all_in_components from hunt_listings where id = $1",
                listing_id,
            )
        )
        amenity = next(
            component
            for component in corrected["components"]
            if component["name"] == "amenity fee"
        )
        assert amenity["amount"] == 18.0
        # Baseline ingest total is 1905 (amenity 10); manual 18 adds 8 → 1913.
        assert corrected["total"] == 1913.0
    finally:
        await _cleanup(pg_pool, hunt_id, property_id, metro)
