from __future__ import annotations

from uuid import uuid4

import asyncpg
import pytest
from manzil_shared.models import Confidence, JobType, TargetScope, UnitApplicability
from manzil_worker.queue import _upsert_floor_plans
from manzil_worker.scoped_facts import append_candidate_resolution, persist_single_source_claims
from manzil_worker.state import FloorPlanIn, RunState, SourceClaim, SourceState


async def _seed_property_source(pool: asyncpg.Pool) -> tuple:  # type: ignore[no-untyped-def]
    property_id = uuid4()
    source_id = uuid4()
    await pool.execute(
        "insert into properties (id, name, canonical_address) values ($1, 'Scoped', '1 Test')",
        property_id,
    )
    await pool.execute(
        "insert into property_sources (id, property_id, url, site_domain) "
        "values ($1, $2, $3, 'example.com')",
        source_id,
        property_id,
        f"https://example.com/{source_id}",
    )
    return property_id, source_id


@pytest.mark.parametrize(
    ("criterion_key", "target_scope", "applicability", "exact"),
    [
        ("exact_fixture", TargetScope.FLOOR_PLAN, UnitApplicability.SPECIFIC_FLOOR_PLANS, True),
        ("all_fixture", TargetScope.PROPERTY, UnitApplicability.ALL_UNITS, False),
        ("select_fixture", TargetScope.PROPERTY, UnitApplicability.SELECT_UNITS, False),
        (
            "unspecified_fixture",
            TargetScope.PROPERTY,
            UnitApplicability.UNIT_SCOPE_UNSPECIFIED,
            False,
        ),
    ],
)
async def test_candidate_resolution_preserves_scope_and_provenance(
    pg_pool: asyncpg.Pool,
    criterion_key: str,
    target_scope: TargetScope,
    applicability: UnitApplicability,
    exact: bool,
) -> None:
    property_id, source_id = await _seed_property_source(pg_pool)
    floor_plan_id = None
    if exact:
        floor_plan_id = await pg_pool.fetchval(
            "insert into floor_plans "
            "(property_id, source_id, plan_name, beds, baths) "
            "values ($1, $2, 'A1', 1, 1) returning id",
            property_id,
            source_id,
        )
    try:
        async with pg_pool.acquire() as conn, conn.transaction():
            candidate_id, resolution_id = await append_candidate_resolution(
                conn,
                property_id=property_id,
                hunt_id=None,
                criterion_key=criterion_key,
                value=True,
                confidence=Confidence.HIGH,
                evidence_quote="listed",
                source_id=source_id,
                origin_key=f"property_source:{source_id}",
                target_scope=target_scope,
                floor_plan_id=floor_plan_id,
                applicability=applicability,
                claim_group_id=uuid4(),
                model="fixture",
                job_id=None,
            )

        current = await pg_pool.fetchrow(
            "select target_scope, floor_plan_id, applicability from current_extractions "
            "where id = $1",
            resolution_id,
        )
        assert dict(current) == {
            "target_scope": target_scope.value,
            "floor_plan_id": floor_plan_id,
            "applicability": applicability.value,
        }
        assert (
            await pg_pool.fetchval(
                "select selected from extraction_resolution_candidates "
                "where resolution_extraction_id = $1 and candidate_extraction_id = $2",
                resolution_id,
                candidate_id,
            )
            is True
        )
    finally:
        await pg_pool.execute("delete from properties where id = $1", property_id)


async def test_current_view_selects_latest_append_only_resolution(
    pg_pool: asyncpg.Pool,
) -> None:
    property_id, source_id = await _seed_property_source(pg_pool)
    try:
        async with pg_pool.acquire() as conn, conn.transaction():
            for value in ("old", "new"):
                await append_candidate_resolution(
                    conn,
                    property_id=property_id,
                    hunt_id=None,
                    criterion_key="pool",
                    value=value,
                    confidence=Confidence.HIGH,
                    evidence_quote=None,
                    source_id=source_id,
                    origin_key=f"property_source:{source_id}",
                    target_scope=TargetScope.PROPERTY,
                    floor_plan_id=None,
                    applicability=None,
                    claim_group_id=uuid4(),
                    model="fixture",
                    job_id=None,
                )

        assert (
            await pg_pool.fetchval(
                "select count(*) from extractions where property_id = $1", property_id
            )
            == 4
        )
        assert (
            await pg_pool.fetchval(
                "select value #>> '{}' from current_extractions "
                "where property_id = $1 and criterion_key = 'pool'",
                property_id,
            )
            == "new"
        )
    finally:
        await pg_pool.execute("delete from properties where id = $1", property_id)


async def test_response_local_floor_plan_reference_resolves_before_persistence(
    pg_pool: asyncpg.Pool,
) -> None:
    property_id, source_id = await _seed_property_source(pg_pool)
    source_url = await pg_pool.fetchval("select url from property_sources where id = $1", source_id)
    floor_plan_id = await pg_pool.fetchval(
        "insert into floor_plans (property_id, source_id, plan_name, beds, baths) "
        "values ($1, $2, 'A1', 1, 1) returning id",
        property_id,
        source_id,
    )
    claim = SourceClaim(
        criterion_key="dishwasher",
        value=True,
        confidence=Confidence.HIGH,
        source_id=source_url,
        model="fixture",
        prompt_version=1,
        target_scope=TargetScope.FLOOR_PLAN,
        floor_plan_ref="response:a1",
        applicability=UnitApplicability.SPECIFIC_FLOOR_PLANS,
    )
    try:
        async with pg_pool.acquire() as conn, conn.transaction():
            await persist_single_source_claims(
                conn,
                property_id=property_id,
                hunt_id=None,
                source_id=source_id,
                source_url=source_url,
                job_id=None,
                claims=[claim],
                floor_plan_ids_by_ref={"response:a1": floor_plan_id},
            )
        row = await pg_pool.fetchrow(
            "select floor_plan_id, applicability from current_extractions "
            "where property_id = $1 and criterion_key = 'dishwasher'",
            property_id,
        )
        assert row["floor_plan_id"] == floor_plan_id
        assert row["applicability"] == "specific_floor_plans"
    finally:
        await pg_pool.execute("delete from properties where id = $1", property_id)


async def test_floor_plan_unit_types_round_trip_through_source_local_upsert(
    pg_pool: asyncpg.Pool,
) -> None:
    property_id, source_id = await _seed_property_source(pg_pool)
    state = RunState(job_id=uuid4(), job_type=JobType.INGEST, url="https://example.com/loft-a")
    state.floor_plans = [
        FloorPlanIn(
            response_key="loft-a",
            plan_name="Loft A",
            beds=1,
            baths=1,
            unit_types=["loft", "apartment"],
        )
    ]
    state.sources = [
        SourceState(
            url="https://example.com/loft-a",
            tier_used=1,
            authoritative_extraction=True,
        )
    ]
    try:
        async with pg_pool.acquire() as conn, conn.transaction():
            _, floor_plan_ids, _ = await _upsert_floor_plans(
                conn,
                property_id=property_id,
                source_id=source_id,
                state=state,
            )
        stored = await pg_pool.fetchval(
            "select unit_types from floor_plans where id = $1", floor_plan_ids[0]
        )
        assert stored == '["loft", "apartment"]'
    finally:
        await pg_pool.execute("delete from properties where id = $1", property_id)


async def test_foreign_floor_plan_target_is_rejected(pg_pool: asyncpg.Pool) -> None:
    property_id, source_id = await _seed_property_source(pg_pool)
    other_property_id, other_source_id = await _seed_property_source(pg_pool)
    other_plan_id = await pg_pool.fetchval(
        "insert into floor_plans (property_id, source_id, plan_name, beds, baths) "
        "values ($1, $2, 'Other', 2, 2) returning id",
        other_property_id,
        other_source_id,
    )
    try:
        async with pg_pool.acquire() as conn:
            with pytest.raises(asyncpg.ForeignKeyViolationError):
                async with conn.transaction():
                    await append_candidate_resolution(
                        conn,
                        property_id=property_id,
                        hunt_id=None,
                        criterion_key="dishwasher",
                        value=True,
                        confidence=Confidence.HIGH,
                        evidence_quote=None,
                        source_id=source_id,
                        origin_key=f"property_source:{source_id}",
                        target_scope=TargetScope.FLOOR_PLAN,
                        floor_plan_id=other_plan_id,
                        applicability=UnitApplicability.SPECIFIC_FLOOR_PLANS,
                        claim_group_id=uuid4(),
                        model="fixture",
                        job_id=None,
                    )
    finally:
        await pg_pool.execute(
            "delete from properties where id = any($1::uuid[])",
            [property_id, other_property_id],
        )


async def test_only_authoritative_refresh_retires_omitted_source_claim(
    pg_pool: asyncpg.Pool,
) -> None:
    property_id, source_id = await _seed_property_source(pg_pool)
    source_url = await pg_pool.fetchval("select url from property_sources where id = $1", source_id)
    initial = SourceClaim(
        criterion_key="utilities_included",
        value=["water"],
        confidence=Confidence.HIGH,
        source_id=source_url,
        model="fixture",
        prompt_version=1,
    )
    try:
        async with pg_pool.acquire() as conn, conn.transaction():
            await persist_single_source_claims(
                conn,
                property_id=property_id,
                hunt_id=None,
                source_id=source_id,
                source_url=source_url,
                job_id=None,
                claims=[initial],
                floor_plan_ids_by_ref={},
                authoritative=True,
            )
            await persist_single_source_claims(
                conn,
                property_id=property_id,
                hunt_id=None,
                source_id=source_id,
                source_url=source_url,
                job_id=None,
                claims=[],
                floor_plan_ids_by_ref={},
                authoritative=False,
            )

        assert (
            await pg_pool.fetchval(
                "select value from current_extractions "
                "where property_id = $1 and criterion_key = 'utilities_included'",
                property_id,
            )
            == '["water"]'
        )

        async with pg_pool.acquire() as conn, conn.transaction():
            await persist_single_source_claims(
                conn,
                property_id=property_id,
                hunt_id=None,
                source_id=source_id,
                source_url=source_url,
                job_id=None,
                claims=[],
                floor_plan_ids_by_ref={},
                authoritative=True,
            )
        retired = await pg_pool.fetchrow(
            "select value, confidence, resolution_rule from current_extractions "
            "where property_id = $1 and criterion_key = 'utilities_included'",
            property_id,
        )
        assert retired["value"] == "null"
        assert retired["confidence"] == "not_found"
        assert retired["resolution_rule"] == "source_refresh_not_found"
    finally:
        await pg_pool.execute("delete from properties where id = $1", property_id)


async def test_authoritative_floor_plan_refresh_retires_only_omitted_source_plans(
    pg_pool: asyncpg.Pool,
) -> None:
    property_id, source_id = await _seed_property_source(pg_pool)
    other_source_id = uuid4()
    await pg_pool.execute(
        "insert into property_sources (id, property_id, url, site_domain) "
        "values ($1, $2, $3, 'other.example')",
        other_source_id,
        property_id,
        f"https://other.example/{other_source_id}",
    )
    omitted_id = await pg_pool.fetchval(
        "insert into floor_plans "
        "(property_id, source_id, source_native_id, plan_name, beds, baths) "
        "values ($1, $2, 'old', 'Old', 1, 1) returning id",
        property_id,
        source_id,
    )
    other_source_plan_id = await pg_pool.fetchval(
        "insert into floor_plans "
        "(property_id, source_id, source_native_id, plan_name, beds, baths) "
        "values ($1, $2, 'other', 'Other', 2, 2) returning id",
        property_id,
        other_source_id,
    )
    state = RunState(
        job_id=uuid4(),
        job_type=JobType.INGEST,
        url="https://example.com",
        sources=[SourceState(url="https://example.com", authoritative_extraction=True)],
        floor_plans=[
            FloorPlanIn(
                response_key="a1",
                source_native_id="new",
                plan_name="New",
                beds=1,
                baths=1,
            )
        ],
    )
    try:
        async with pg_pool.acquire() as conn, conn.transaction():
            _, new_ids, _ = await _upsert_floor_plans(
                conn,
                property_id=property_id,
                source_id=source_id,
                state=state,
            )

        rows = {
            row["id"]: row["is_current"]
            for row in await pg_pool.fetch(
                "select id, is_current from floor_plans where property_id = $1",
                property_id,
            )
        }
        assert rows[omitted_id] is False
        assert rows[other_source_plan_id] is True
        assert rows[new_ids[0]] is True
    finally:
        await pg_pool.execute("delete from properties where id = $1", property_id)
