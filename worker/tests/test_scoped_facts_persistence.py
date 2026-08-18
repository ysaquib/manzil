from __future__ import annotations

import json
from uuid import uuid4

import asyncpg
import pytest
from manzil_shared.models import Confidence, JobType, TargetScope, UnitApplicability
from manzil_worker.queue import _upsert_floor_plans
from manzil_worker.scoped_facts import (
    append_candidate_resolution,
    persist_reconciled_claims,
    persist_single_source_claims,
)
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


async def test_typed_claim_variants_remain_independently_current(
    pg_pool: asyncpg.Pool,
) -> None:
    property_id, source_id = await _seed_property_source(pg_pool)
    try:
        async with pg_pool.acquire() as conn, conn.transaction():
            for value, applicability in (
                ("carport", UnitApplicability.ALL_UNITS),
                ("garage", UnitApplicability.SELECT_UNITS),
            ):
                await append_candidate_resolution(
                    conn,
                    property_id=property_id,
                    hunt_id=None,
                    criterion_key="parking",
                    value=value,
                    confidence=Confidence.HIGH,
                    evidence_quote=value,
                    source_id=source_id,
                    origin_key=f"property_source:{source_id}",
                    target_scope=TargetScope.PROPERTY,
                    floor_plan_id=None,
                    applicability=applicability,
                    claim_group_id=uuid4(),
                    model="fixture",
                    job_id=None,
                )

        rows = await pg_pool.fetch(
            "select claim_variant, value #>> '{}' as value, applicability "
            "from current_extractions "
            "where property_id = $1 and criterion_key = 'parking' "
            "order by claim_variant",
            property_id,
        )
        assert [tuple(row) for row in rows] == [
            ("carport", "carport", "all_units"),
            ("garage", "garage", "select_units"),
        ]
    finally:
        await pg_pool.execute("delete from properties where id = $1", property_id)


async def test_flooring_set_variants_remain_independently_current(
    pg_pool: asyncpg.Pool,
) -> None:
    property_id, source_id = await _seed_property_source(pg_pool)
    try:
        async with pg_pool.acquire() as conn, conn.transaction():
            for value, applicability in (
                (["vinyl"], UnitApplicability.ALL_UNITS),
                (["hardwood", "carpet"], UnitApplicability.UNIT_SCOPE_UNSPECIFIED),
            ):
                await append_candidate_resolution(
                    conn,
                    property_id=property_id,
                    hunt_id=None,
                    criterion_key="flooring_materials",
                    value=value,
                    confidence=Confidence.HIGH,
                    evidence_quote=", ".join(value),
                    source_id=source_id,
                    origin_key=f"property_source:{source_id}",
                    target_scope=TargetScope.PROPERTY,
                    floor_plan_id=None,
                    applicability=applicability,
                    claim_group_id=uuid4(),
                    model="fixture",
                    job_id=None,
                )

        rows = await pg_pool.fetch(
            "select value, applicability from current_extractions "
            "where property_id = $1 and criterion_key = 'flooring_materials' "
            "order by applicability",
            property_id,
        )
        assert [(row["value"], row["applicability"]) for row in rows] == [
            ('["vinyl"]', "all_units"),
            ('["hardwood", "carpet"]', "unit_scope_unspecified"),
        ]
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


async def test_multi_source_resolution_links_every_candidate(
    pg_pool: asyncpg.Pool,
) -> None:
    property_id, first_source_id = await _seed_property_source(pg_pool)
    first_url = await pg_pool.fetchval(
        "select url from property_sources where id = $1", first_source_id
    )
    second_source_id = uuid4()
    second_url = f"https://second.example/{second_source_id}"
    await pg_pool.execute(
        "insert into property_sources (id, property_id, url, site_domain) "
        "values ($1, $2, $3, 'second.example')",
        second_source_id,
        property_id,
        second_url,
    )
    first = SourceClaim(
        criterion_key="pets_policy",
        value="cats_and_dogs",
        confidence=Confidence.HIGH,
        evidence_quote="Pets welcome",
        source_id=first_url,
        model="fixture",
        prompt_version=1,
    )
    second = SourceClaim(
        criterion_key="pets_policy",
        value="cats_only",
        confidence=Confidence.MEDIUM,
        evidence_quote="Cats welcome",
        source_id=second_url,
        model="fixture",
        prompt_version=1,
    )
    resolution = first.model_copy(
        update={
            "resolution_rule": "family_majority",
            "candidate_claim_group_ids": [
                first.claim_group_id,
                second.claim_group_id,
            ],
        }
    )
    try:
        async with pg_pool.acquire() as conn, conn.transaction():
            await persist_reconciled_claims(
                conn,
                property_id=property_id,
                hunt_id=None,
                job_id=None,
                candidate_claims=[first, second],
                resolved_claims=[resolution],
                source_ids_by_url={
                    first_url: first_source_id,
                    second_url: second_source_id,
                },
                floor_plan_ids_by_source_ref={},
            )
        rows = await pg_pool.fetch(
            """
            select candidate.value #>> '{}' as value, edge.selected
            from current_extractions resolved
            join extraction_resolution_candidates edge
              on edge.resolution_extraction_id = resolved.id
            join extractions candidate on candidate.id = edge.candidate_extraction_id
            where resolved.property_id = $1 and resolved.criterion_key = 'pets_policy'
            order by value
            """,
            property_id,
        )
        assert [(row["value"], row["selected"]) for row in rows] == [
            ("cats_and_dogs", True),
            ("cats_only", False),
        ]
    finally:
        await pg_pool.execute("delete from properties where id = $1", property_id)


async def test_authoritative_source_omission_retires_only_that_candidate(
    pg_pool: asyncpg.Pool,
) -> None:
    property_id, first_source_id = await _seed_property_source(pg_pool)
    first_url = await pg_pool.fetchval(
        "select url from property_sources where id = $1", first_source_id
    )
    second_source_id = uuid4()
    second_url = f"https://second.example/{second_source_id}"
    await pg_pool.execute(
        "insert into property_sources (id, property_id, url, site_domain) "
        "values ($1, $2, $3, 'second.example')",
        second_source_id,
        property_id,
        second_url,
    )

    def claim(url: str) -> SourceClaim:
        return SourceClaim(
            criterion_key="pool",
            value=True,
            confidence=Confidence.HIGH,
            source_id=url,
            model="fixture",
            prompt_version=1,
        )

    first, second = claim(first_url), claim(second_url)
    initial_resolution = first.model_copy(
        update={
            "resolution_rule": "family_supermajority",
            "candidate_claim_group_ids": [
                first.claim_group_id,
                second.claim_group_id,
            ],
        }
    )
    refreshed_second = claim(second_url)
    refreshed_resolution = refreshed_second.model_copy(
        update={
            "resolution_rule": "single_source",
            "candidate_claim_group_ids": [refreshed_second.claim_group_id],
        }
    )
    source_ids = {
        first_url: first_source_id,
        second_url: second_source_id,
    }
    try:
        async with pg_pool.acquire() as conn, conn.transaction():
            await persist_reconciled_claims(
                conn,
                property_id=property_id,
                hunt_id=None,
                job_id=None,
                candidate_claims=[first, second],
                resolved_claims=[initial_resolution],
                source_ids_by_url=source_ids,
                floor_plan_ids_by_source_ref={},
            )
            await persist_reconciled_claims(
                conn,
                property_id=property_id,
                hunt_id=None,
                job_id=None,
                candidate_claims=[refreshed_second],
                resolved_claims=[refreshed_resolution],
                source_ids_by_url=source_ids,
                floor_plan_ids_by_source_ref={},
                authoritative_source_urls=[first_url, second_url],
            )
        first_candidate = await pg_pool.fetchrow(
            "select value, confidence from current_extraction_candidates "
            "where property_id = $1 and source_id = $2 and criterion_key = 'pool'",
            property_id,
            first_source_id,
        )
        assert json.loads(first_candidate["value"]) is None
        assert first_candidate["confidence"] == Confidence.NOT_FOUND.value
        assert (
            await pg_pool.fetchval(
                "select value from current_extractions "
                "where property_id = $1 and criterion_key = 'pool'",
                property_id,
            )
            == "true"
        )
    finally:
        await pg_pool.execute("delete from properties where id = $1", property_id)


async def test_shared_claim_group_persists_once_per_target_floor_plan(
    pg_pool: asyncpg.Pool,
) -> None:
    property_id, source_id = await _seed_property_source(pg_pool)
    source_url = await pg_pool.fetchval("select url from property_sources where id = $1", source_id)
    plan_ids = await pg_pool.fetch(
        "insert into floor_plans (property_id, source_id, plan_name, beds, baths) "
        "values ($1, $2, 'A1', 1, 1), ($1, $2, 'B1', 2, 1) returning id, plan_name",
        property_id,
        source_id,
    )
    ids_by_ref = {f"response:{row['plan_name'].lower()}": row["id"] for row in plan_ids}
    group_id = uuid4()
    claims = [
        SourceClaim(
            criterion_key="dishwasher",
            value=True,
            confidence=Confidence.HIGH,
            evidence_quote="A1 and B1 include dishwashers",
            source_id=source_url,
            model="fixture",
            prompt_version=1,
            target_scope=TargetScope.FLOOR_PLAN,
            floor_plan_ref=ref,
            applicability=UnitApplicability.SPECIFIC_FLOOR_PLANS,
            claim_group_id=group_id,
        )
        for ref in ids_by_ref
    ]
    try:
        async with pg_pool.acquire() as conn, conn.transaction():
            await persist_reconciled_claims(
                conn,
                property_id=property_id,
                hunt_id=None,
                job_id=None,
                candidate_claims=claims,
                resolved_claims=[
                    claim.model_copy(
                        update={
                            "resolution_rule": "single_source",
                            "candidate_claim_group_ids": [group_id],
                        }
                    )
                    for claim in claims
                ],
                source_ids_by_url={source_url: source_id},
                floor_plan_ids_by_source_ref={
                    (source_url, ref): floor_plan_id for ref, floor_plan_id in ids_by_ref.items()
                },
            )
        rows = await pg_pool.fetch(
            "select floor_plan_id, claim_group_id from current_extraction_candidates "
            "where property_id = $1 and criterion_key = 'dishwasher'",
            property_id,
        )
        assert {row["floor_plan_id"] for row in rows} == set(ids_by_ref.values())
        assert {row["claim_group_id"] for row in rows} == {group_id}
        assert (
            await pg_pool.fetchval(
                """
                select count(*)
                from current_extractions resolved
                join extraction_resolution_candidates edge
                  on edge.resolution_extraction_id = resolved.id
                where resolved.property_id = $1
                  and resolved.criterion_key = 'dishwasher'
                  and edge.selected
                """,
                property_id,
            )
            == 2
        )
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


async def test_authoritative_refresh_keeps_known_resolution_when_source_omits_it(
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
        retained = await pg_pool.fetchrow(
            "select value, confidence, resolution_rule from current_extractions "
            "where property_id = $1 and criterion_key = 'utilities_included'",
            property_id,
        )
        assert retained["value"] == '["water"]'
        assert retained["confidence"] == "high"
        assert retained["resolution_rule"] == "single_source"
        candidate = await pg_pool.fetchrow(
            "select value, confidence from current_extraction_candidates "
            "where property_id = $1 and criterion_key = 'utilities_included'",
            property_id,
        )
        assert candidate["value"] == "null"
        assert candidate["confidence"] == "not_found"
    finally:
        await pg_pool.execute("delete from properties where id = $1", property_id)


async def test_authoritative_refresh_replaces_a_known_value_only_with_a_changed_known_value(
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
    updated = initial.model_copy(update={"value": ["water", "trash"]})
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
                claims=[updated],
                floor_plan_ids_by_ref={},
                authoritative=True,
            )

        assert (
            await pg_pool.fetchval(
                "select value from current_extractions "
                "where property_id = $1 and criterion_key = 'utilities_included'",
                property_id,
            )
            == '["water", "trash"]'
        )
    finally:
        await pg_pool.execute("delete from properties where id = $1", property_id)


async def test_authoritative_refresh_fills_a_preexisting_unknown_resolution(
    pg_pool: asyncpg.Pool,
) -> None:
    property_id, source_id = await _seed_property_source(pg_pool)
    source_url = await pg_pool.fetchval("select url from property_sources where id = $1", source_id)
    unknown = SourceClaim(
        criterion_key="utilities_included",
        value=None,
        confidence=Confidence.NOT_FOUND,
        source_id=source_url,
        model="fixture",
        prompt_version=1,
    )
    known = unknown.model_copy(update={"value": ["water"], "confidence": Confidence.HIGH})
    try:
        async with pg_pool.acquire() as conn, conn.transaction():
            await persist_single_source_claims(
                conn,
                property_id=property_id,
                hunt_id=None,
                source_id=source_id,
                source_url=source_url,
                job_id=None,
                claims=[unknown],
                floor_plan_ids_by_ref={},
            )
            await persist_single_source_claims(
                conn,
                property_id=property_id,
                hunt_id=None,
                source_id=source_id,
                source_url=source_url,
                job_id=None,
                claims=[known],
                floor_plan_ids_by_ref={},
                authoritative=True,
            )

        assert (
            await pg_pool.fetchval(
                "select value from current_extractions "
                "where property_id = $1 and criterion_key = 'utilities_included'",
                property_id,
            )
            == '["water"]'
        )
    finally:
        await pg_pool.execute("delete from properties where id = $1", property_id)


async def test_floor_plan_refresh_keeps_known_columns_when_new_values_are_missing(
    pg_pool: asyncpg.Pool,
) -> None:
    property_id, source_id = await _seed_property_source(pg_pool)
    source_url = await pg_pool.fetchval("select url from property_sources where id = $1", source_id)
    initial = RunState(
        job_id=uuid4(),
        job_type=JobType.INGEST,
        url=source_url,
        sources=[SourceState(url=source_url, authoritative_extraction=True)],
        floor_plans=[
            FloorPlanIn(
                response_key="a1",
                source_native_id="a1",
                plan_name="A1",
                beds=1,
                baths=1,
                unit_types=["apartment"],
                sqft_min=700,
                sqft_max=725,
                rent_min=1500,
                rent_max=1550,
                deposit=500,
                availability_date="2026-09-01",
            )
        ],
    )
    refreshed = RunState(
        job_id=uuid4(),
        job_type=JobType.REFRESH,
        url=source_url,
        sources=[SourceState(url=source_url, authoritative_extraction=True)],
        floor_plans=[
            FloorPlanIn(
                response_key="a1",
                source_native_id="a1",
                plan_name="A1",
                beds=1,
                baths=1,
            )
        ],
    )
    try:
        async with pg_pool.acquire() as conn, conn.transaction():
            await _upsert_floor_plans(
                conn,
                property_id=property_id,
                source_id=source_id,
                state=initial,
            )
            _, floor_plan_ids, _ = await _upsert_floor_plans(
                conn,
                property_id=property_id,
                source_id=source_id,
                state=refreshed,
            )
        row = await pg_pool.fetchrow(
            "select unit_types, sqft_min, sqft_max, rent_min, rent_max, deposit, availability_date "
            "from floor_plans where id = $1",
            floor_plan_ids[0],
        )
        assert row["unit_types"] == '["apartment"]'
        assert (row["sqft_min"], row["sqft_max"]) == (700, 725)
        assert (float(row["rent_min"]), float(row["rent_max"])) == (1500, 1550)
        assert float(row["deposit"]) == 500
        assert row["availability_date"].isoformat() == "2026-09-01"
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
