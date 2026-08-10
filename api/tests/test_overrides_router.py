"""P1-8 overrides router tests."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from api_helpers import FAKE_USER
from httpx import AsyncClient


async def _seed_listing(db_pool):  # type: ignore[no-untyped-def]
    hunt_id, listing_id, property_id = uuid4(), uuid4(), uuid4()
    await db_pool.execute(
        "insert into hunts (id, name, owner_id) values ($1, 'O', $2)",
        hunt_id,
        FAKE_USER.id,
    )
    await db_pool.execute(
        "insert into properties (id, name, canonical_address) values ($1, 'P', 'a')",
        property_id,
    )
    await db_pool.execute(
        """
        insert into hunt_listings (id, hunt_id, property_id, added_by)
        values ($1, $2, $3, $4)
        """,
        listing_id,
        hunt_id,
        property_id,
        FAKE_USER.id,
    )
    return hunt_id, listing_id, property_id


@pytest.mark.asyncio
async def test_create_override_enqueues_rescore(client: AsyncClient, db_pool) -> None:
    hunt_id, listing_id, property_id = await _seed_listing(db_pool)
    try:
        resp = await client.post(
            f"/v1/listings/{listing_id}/overrides",
            json={"criterion_key": "beds", "value": 2, "note": "manual"},
        )
        assert resp.status_code == 201
        assert resp.json()["user_id"] == FAKE_USER.id
        count = await db_pool.fetchval(
            "select count(*) from overrides where hunt_listing_id = $1", listing_id
        )
        assert count == 1
        rescore = await db_pool.fetchval(
            "select count(*) from jobs where type = 'rescore' and payload->>'hunt_id' = $1",
            str(hunt_id),
        )
        assert rescore == 1
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)
        await db_pool.execute("delete from properties where id = $1", property_id)


@pytest.mark.asyncio
async def test_create_exact_floor_plan_override(client: AsyncClient, db_pool) -> None:
    hunt_id, listing_id, property_id = await _seed_listing(db_pool)
    source_id = await db_pool.fetchval(
        "insert into property_sources (property_id, url, site_domain) "
        "values ($1, $2, 'example.com') returning id",
        property_id,
        f"https://example.com/{uuid4()}",
    )
    floor_plan_id = await db_pool.fetchval(
        "insert into floor_plans (property_id, source_id, plan_name, beds, baths) "
        "values ($1, $2, 'A1', 1, 1) returning id",
        property_id,
        source_id,
    )
    try:
        resp = await client.post(
            f"/v1/listings/{listing_id}/overrides",
            json={
                "criterion_key": "dishwasher",
                "value": True,
                "target_scope": "floor_plan",
                "floor_plan_id": str(floor_plan_id),
                "applicability": "specific_floor_plans",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["floor_plan_id"] == str(floor_plan_id)
        assert resp.json()["target_scope"] == "floor_plan"
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)
        await db_pool.execute("delete from properties where id = $1", property_id)


@pytest.mark.asyncio
async def test_rejects_floor_plan_from_another_property(client: AsyncClient, db_pool) -> None:
    hunt_id, listing_id, property_id = await _seed_listing(db_pool)
    other_property_id = await db_pool.fetchval(
        "insert into properties (name, canonical_address) values ('Other', 'b') returning id"
    )
    source_id = await db_pool.fetchval(
        "insert into property_sources (property_id, url, site_domain) "
        "values ($1, $2, 'example.com') returning id",
        other_property_id,
        f"https://example.com/{uuid4()}",
    )
    foreign_plan_id = await db_pool.fetchval(
        "insert into floor_plans (property_id, source_id, plan_name, beds, baths) "
        "values ($1, $2, 'B2', 2, 2) returning id",
        other_property_id,
        source_id,
    )
    try:
        resp = await client.post(
            f"/v1/listings/{listing_id}/overrides",
            json={
                "criterion_key": "dishwasher",
                "value": True,
                "target_scope": "floor_plan",
                "floor_plan_id": str(foreign_plan_id),
                "applicability": "specific_floor_plans",
            },
        )
        assert resp.status_code == 422
        assert resp.json()["code"] == "invalid_override_target"
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)
        await db_pool.execute(
            "delete from properties where id = any($1::uuid[])",
            [property_id, other_property_id],
        )


async def _seed_manual_criterion(db_pool, hunt_id, *, fact_scope="property"):  # type: ignore[no-untyped-def]
    """A manual custom Criterion: no producer, so the Override is its only input."""
    custom_key = f"custom:{uuid4()}"
    await db_pool.execute(
        """
        insert into rubric_criteria (hunt_id, custom_def, options)
        values ($1, $2::jsonb, $3::jsonb)
        """,
        hunt_id,
        json.dumps(
            {
                "schema_version": 1,
                "key": custom_key,
                "label": "Landlord was straight with us",
                "description": "How the leasing agent came across on the phone.",
                "fact_scope": fact_scope,
                "value_schema": {"type": "string", "enum": ["evasive", "fine", "great"]},
                "acquisition": "manual",
                "requires_tool": None,
                "refresh_class": "manual",
                "routing_confirmed": True,
            }
        ),
        json.dumps([{"match": {"op": "eq", "value": "great"}, "delta": 1}]),
    )
    return custom_key


@pytest.mark.asyncio
async def test_manual_override_accepts_a_value_inside_the_authored_schema(
    client: AsyncClient, db_pool
) -> None:
    hunt_id, listing_id, property_id = await _seed_listing(db_pool)
    custom_key = await _seed_manual_criterion(db_pool, hunt_id)
    try:
        resp = await client.post(
            f"/v1/listings/{listing_id}/overrides",
            json={"criterion_key": custom_key, "value": "great"},
        )
        assert resp.status_code == 201, resp.text
        stored = await db_pool.fetchval(
            "select value from overrides where hunt_listing_id = $1 and criterion_key = $2",
            listing_id,
            custom_key,
        )
        assert (json.loads(stored) if isinstance(stored, str) else stored) == "great"
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)
        await db_pool.execute("delete from properties where id = $1", property_id)


@pytest.mark.asyncio
async def test_manual_override_rejects_a_value_outside_the_authored_schema(
    client: AsyncClient, db_pool
) -> None:
    """Unvalidated, an off-schema value would score as 'matched nothing' — delta 0,
    indistinguishable from a considered answer. It must fail loudly instead."""
    hunt_id, listing_id, property_id = await _seed_listing(db_pool)
    custom_key = await _seed_manual_criterion(db_pool, hunt_id)
    try:
        resp = await client.post(
            f"/v1/listings/{listing_id}/overrides",
            json={"criterion_key": custom_key, "value": "sensational"},
        )
        assert resp.status_code == 422, resp.text
        assert resp.json()["code"] == "invalid_override_value"
        count = await db_pool.fetchval(
            "select count(*) from overrides where hunt_listing_id = $1", listing_id
        )
        assert count == 0
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)
        await db_pool.execute("delete from properties where id = $1", property_id)


@pytest.mark.asyncio
async def test_manual_override_rejects_a_scope_the_criterion_does_not_use(
    client: AsyncClient, db_pool
) -> None:
    hunt_id, listing_id, property_id = await _seed_listing(db_pool)
    custom_key = await _seed_manual_criterion(db_pool, hunt_id, fact_scope="floor_plan")
    source_id = await db_pool.fetchval(
        "insert into property_sources (property_id, url, site_domain) "
        "values ($1, $2, 'example.com') returning id",
        property_id,
        f"https://example.com/{uuid4()}",
    )
    await db_pool.execute(
        "insert into floor_plans (property_id, source_id, plan_name, beds, baths) "
        "values ($1, $2, 'A1', 1, 1)",
        property_id,
        source_id,
    )
    try:
        resp = await client.post(
            f"/v1/listings/{listing_id}/overrides",
            json={"criterion_key": custom_key, "value": "great"},
        )
        assert resp.status_code == 422, resp.text
        assert resp.json()["code"] == "invalid_override_value"
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)
        await db_pool.execute("delete from properties where id = $1", property_id)


@pytest.mark.asyncio
async def test_catalog_override_values_are_not_schema_checked(client: AsyncClient, db_pool) -> None:
    """Validation is scoped to manual custom Criteria: for an extracted Criterion
    the pipeline is the input path, and today's Override behaviour is unchanged."""
    hunt_id, listing_id, property_id = await _seed_listing(db_pool)
    try:
        resp = await client.post(
            f"/v1/listings/{listing_id}/overrides",
            json={"criterion_key": "beds", "value": "not-a-number"},
        )
        assert resp.status_code == 201, resp.text
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)
        await db_pool.execute("delete from properties where id = $1", property_id)


@pytest.mark.asyncio
async def test_manual_answer_can_be_reverted_with_a_null_tombstone(
    client: AsyncClient, db_pool
) -> None:
    """A null Override is the §9.6 tombstone that returns a Criterion to unknown.
    Schema-checking it would make a manual answer permanently unrevertable."""
    hunt_id, listing_id, property_id = await _seed_listing(db_pool)
    custom_key = await _seed_manual_criterion(db_pool, hunt_id)
    try:
        answered = await client.post(
            f"/v1/listings/{listing_id}/overrides",
            json={"criterion_key": custom_key, "value": "great"},
        )
        assert answered.status_code == 201, answered.text
        reverted = await client.post(
            f"/v1/listings/{listing_id}/overrides",
            json={"criterion_key": custom_key, "value": None},
        )
        assert reverted.status_code == 201, reverted.text
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)
        await db_pool.execute("delete from properties where id = $1", property_id)


@pytest.mark.asyncio
async def test_an_unparseable_sibling_definition_does_not_block_an_override(
    client: AsyncClient, db_pool
) -> None:
    """One Rubric row this build cannot parse is a Rubric problem. It must not
    refuse an Override for a different, perfectly valid Criterion."""
    hunt_id, listing_id, property_id = await _seed_listing(db_pool)
    good_key = await _seed_manual_criterion(db_pool, hunt_id)
    await db_pool.execute(
        "insert into rubric_criteria (hunt_id, custom_def, options) values ($1, $2::jsonb, '[]')",
        hunt_id,
        json.dumps(
            {
                "schema_version": 1,
                "key": f"custom:{uuid4()}",
                "label": "Legacy",
                "description": "Stored under a looser schema than this build accepts.",
                "fact_scope": "property",
                "value_schema": {"type": "string", "enum": ["only-one"]},
                "requires_tool": None,
                "refresh_class": "listing_details",
                "routing_confirmed": True,
            }
        ),
    )
    try:
        resp = await client.post(
            f"/v1/listings/{listing_id}/overrides",
            json={"criterion_key": good_key, "value": "great"},
        )
        assert resp.status_code == 201, resp.text
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)
        await db_pool.execute("delete from properties where id = $1", property_id)
