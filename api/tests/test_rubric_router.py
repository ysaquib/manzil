"""P1-5 rubric router tests."""

from __future__ import annotations

from uuid import uuid4

import pytest
from api_helpers import FAKE_USER
from httpx import AsyncClient
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
