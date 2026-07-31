"""P1-5 rubric router tests."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from api_helpers import FAKE_USER
from httpx import AsyncClient
from manzil_api.rubric import service
from manzil_worker.phase0_rubric import phase0_rubric


@pytest.mark.asyncio
async def test_put_rubric_invalid_option_rejected(client: AsyncClient, db_pool) -> None:
    hunt_id = uuid4()
    await db_pool.execute(
        "insert into hunts (id, name, owner_id, settings) values ($1, 'R', $2, '{}'::jsonb)",
        hunt_id,
        FAKE_USER.id,
    )
    try:
        bad = {
            "criteria": [
                {
                    "catalog_key": "beds",
                    "options": [{"match": {"op": "eq", "value": "not-a-number"}, "delta": 1.0}],
                    "position": 0,
                }
            ]
        }
        resp = await client.put(f"/v1/hunts/{hunt_id}/rubric", json=bad)
        assert resp.status_code == 422
        assert resp.json()["code"] == "invalid_rubric_option"
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)


@pytest.mark.asyncio
async def test_put_rubric_bumps_version_and_enqueues_rescore(client: AsyncClient, db_pool) -> None:
    hunt_id = uuid4()
    await db_pool.execute(
        """
        insert into hunts (id, name, owner_id, settings, rubric_version)
        values ($1, 'R', $2, '{}'::jsonb, 0)
        """,
        hunt_id,
        FAKE_USER.id,
    )
    try:
        criteria = []
        for crit in phase0_rubric():
            criteria.append(
                {
                    "catalog_key": crit.catalog_key,
                    "options": [o.model_dump(mode="json") for o in crit.options],
                    "unknown_delta": crit.unknown_delta,
                    "non_negotiable": crit.non_negotiable.model_dump(mode="json")
                    if crit.non_negotiable
                    else None,
                    "position": crit.position,
                }
            )
        resp = await client.put(f"/v1/hunts/{hunt_id}/rubric", json={"criteria": criteria})
        assert resp.status_code == 200
        version = await db_pool.fetchval("select rubric_version from hunts where id = $1", hunt_id)
        assert version == 1
        rescore = await db_pool.fetchval(
            "select count(*) from jobs where type = 'rescore' and payload->>'hunt_id' = $1",
            str(hunt_id),
        )
        assert rescore == 1
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)


@pytest.mark.asyncio
async def test_put_rubric_derives_dealbreaker_as_not_bonus(client: AsyncClient, db_pool) -> None:
    hunt_id = uuid4()
    await db_pool.execute(
        "insert into hunts (id, name, owner_id) values ($1, 'Bonus', $2)", hunt_id, FAKE_USER.id
    )
    try:
        response = await client.put(
            f"/v1/hunts/{hunt_id}/rubric",
            json={
                "criteria": [
                    {
                        "catalog_key": "beds",
                        "options": [
                            {
                                "match": {"op": "gte", "value": 2},
                                "delta": 1,
                                "dealbreaker_set_score": 0,
                            }
                        ],
                        "unknown_delta": 0,
                        "is_bonus": True,
                    }
                ]
            },
        )
        assert response.status_code == 200
        assert response.json()[0]["is_bonus"] is False
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)


@pytest.mark.asyncio
async def test_put_rubric_validates_array_set_operators(client: AsyncClient, db_pool) -> None:
    hunt_id = uuid4()
    await db_pool.execute(
        "insert into hunts (id, name, owner_id) values ($1, 'Array rubric', $2)",
        hunt_id,
        FAKE_USER.id,
    )
    try:
        valid = await client.put(
            f"/v1/hunts/{hunt_id}/rubric",
            json={
                "criteria": [
                    {
                        "catalog_key": "property_types",
                        "options": [
                            {
                                "match": {
                                    "op": "contains_any",
                                    "value": ["townhome", "duplex"],
                                },
                                "delta": 0.5,
                            }
                        ],
                    }
                ]
            },
        )
        assert valid.status_code == 200

        for match in (
            {"op": "contains_all", "value": []},
            {"op": "contains_any", "value": ["castle"]},
            {"op": "eq", "value": ["townhome"]},
        ):
            response = await client.put(
                f"/v1/hunts/{hunt_id}/rubric",
                json={
                    "criteria": [
                        {
                            "catalog_key": "property_types",
                            "options": [{"match": match, "delta": 0.5}],
                        }
                    ]
                },
            )
            assert response.status_code == 422, match
            assert response.json()["code"] == "invalid_rubric_option"
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)


@pytest.mark.asyncio
async def test_custom_routing_is_traced_through_the_llm_seam(
    client: AsyncClient, db_pool, monkeypatch
) -> None:
    hunt_id = uuid4()
    await db_pool.execute(
        "insert into hunts (id, name, owner_id) values ($1, 'Custom route', $2)",
        hunt_id,
        FAKE_USER.id,
    )
    calls = []

    async def fake_call(stage, schema, content):  # type: ignore[no-untyped-def]
        calls.append((stage, content))
        return schema.model_validate(
            {
                "requires_tool": "maps",
                "reason": "The answer depends on distance to a named destination.",
            }
        )

    monkeypatch.setattr(service, "llm_call_structured", fake_call)
    try:
        response = await client.post(
            f"/v1/hunts/{hunt_id}/rubric/custom-routing",
            json={
                "label": "Close to work",
                "description": "Is the Property within 20 minutes of downtown?",
            },
        )
        assert response.status_code == 200
        assert response.json()["suggested_requires_tool"] == "maps"
        assert response.json()["supported"] is True
        assert response.json()["key"].startswith("custom:")
        assert calls[0][0] == "custom_route"
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)


@pytest.mark.asyncio
async def test_new_custom_criterion_enqueues_active_listing_backfill(
    client: AsyncClient, db_pool
) -> None:
    hunt_id, property_id, listing_id = uuid4(), uuid4(), uuid4()
    custom_key = f"custom:{uuid4()}"
    await db_pool.execute(
        "insert into hunts (id, name, owner_id) values ($1, 'Custom backfill', $2)",
        hunt_id,
        FAKE_USER.id,
    )
    await db_pool.execute(
        "insert into properties (id, name, canonical_address) values ($1, 'P', '1 Main St')",
        property_id,
    )
    source_id = await db_pool.fetchval(
        """
        insert into property_sources (property_id, url, site_domain)
        values ($1, 'https://custom.example/p', 'custom.example')
        returning id
        """,
        property_id,
    )
    await db_pool.execute(
        """
        insert into hunt_listings
            (id, hunt_id, property_id, added_by, submitted_source_id)
        values ($1, $2, $3, $4, $5)
        """,
        listing_id,
        hunt_id,
        property_id,
        FAKE_USER.id,
        source_id,
    )
    try:
        response = await client.put(
            f"/v1/hunts/{hunt_id}/rubric",
            json={
                "criteria": [
                    {
                        "custom_def": {
                            "schema_version": 1,
                            "key": custom_key,
                            "label": "Quiet hours",
                            "description": "Whether quiet hours are stated.",
                            "fact_scope": "property",
                            "value_schema": {"type": "boolean"},
                            "requires_tool": None,
                            "refresh_class": "listing_details",
                            "routing_confirmed": True,
                        },
                        "options": [{"match": {"op": "bool", "value": True}, "delta": 1}],
                    }
                ]
            },
        )
        assert response.status_code == 200, response.text
        payload = await db_pool.fetchval(
            """
            select payload from jobs
            where hunt_listing_id = $1 and type = 'refresh'
            order by created_at desc limit 1
            """,
            listing_id,
        )
        if isinstance(payload, str):
            payload = json.loads(payload)
        assert payload["scope"] == "custom_match"
        assert payload["custom_criterion_keys"] == [custom_key]
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)
        await db_pool.execute("delete from properties where id = $1", property_id)
