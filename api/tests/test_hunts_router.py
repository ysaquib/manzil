"""P1-5 hunts router tests."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from api_helpers import FAKE_USER
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_hunt_inserts_owner_member(client: AsyncClient, db_pool) -> None:
    resp = await client.post("/v1/hunts", json={"name": "My Hunt"})
    assert resp.status_code == 201
    hunt_id = resp.json()["id"]
    try:
        member = await db_pool.fetchrow(
            "select role from hunt_members where hunt_id = $1 and user_id = $2",
            hunt_id,
            FAKE_USER.id,
        )
        assert member is not None
        assert member["role"] == "owner"
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)


@pytest.mark.asyncio
async def test_settings_min_confidence_bumps_version_and_rescore(
    client: AsyncClient, db_pool
) -> None:
    hunt_id = uuid4()
    settings = {
        "default_source_policy": "tiers_1_2_3",
        "cost_estimate_mode": "conservative",
        "min_confidence": "medium",
        "proximity_mode": "driving",
    }
    await db_pool.execute(
        """
        insert into hunts (id, name, owner_id, settings, rubric_version)
        values ($1, 'S', $2, $3::jsonb, 0)
        """,
        hunt_id,
        FAKE_USER.id,
        json.dumps(settings),
    )
    try:
        resp = await client.patch(
            f"/v1/hunts/{hunt_id}/settings",
            json={"settings": {"min_confidence": "low"}},
        )
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
async def test_settings_unknown_key_rejected(client: AsyncClient, db_pool) -> None:
    hunt_id = uuid4()
    await db_pool.execute(
        "insert into hunts (id, name, owner_id) values ($1, 'S', $2)",
        hunt_id,
        FAKE_USER.id,
    )
    try:
        resp = await client.patch(
            f"/v1/hunts/{hunt_id}/settings",
            json={"settings": {"bogus_key": "x"}},
        )
        assert resp.status_code == 422
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)


_FULL_SETTINGS = {
    "default_source_policy": "tiers_1_2_3",
    "cost_estimate_mode": "conservative",
    "min_confidence": "medium",
    "proximity_mode": "driving",
    "occupants": 1,
    "cats": 0,
    "dogs": 0,
}


async def _seed_hunt(db_pool, settings: dict) -> str:  # type: ignore[no-untyped-def]
    hunt_id = uuid4()
    await db_pool.execute(
        """
        insert into hunts (id, name, owner_id, settings, rubric_version)
        values ($1, 'S', $2, $3::jsonb, 0)
        """,
        hunt_id,
        FAKE_USER.id,
        json.dumps(settings),
    )
    return str(hunt_id)


@pytest.mark.asyncio
async def test_settings_household_valid_update(client: AsyncClient, db_pool) -> None:
    hunt_id = await _seed_hunt(db_pool, _FULL_SETTINGS)
    try:
        resp = await client.patch(
            f"/v1/hunts/{hunt_id}/settings",
            json={"settings": {"occupants": 3, "cats": 2, "dogs": 1}},
        )
        assert resp.status_code == 200
        saved = resp.json()["settings"]
        assert saved["occupants"] == 3
        assert saved["cats"] == 2
        assert saved["dogs"] == 1
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)


@pytest.mark.asyncio
async def test_settings_household_out_of_range_rejected(client: AsyncClient, db_pool) -> None:
    hunt_id = await _seed_hunt(db_pool, _FULL_SETTINGS)
    try:
        resp = await client.patch(f"/v1/hunts/{hunt_id}/settings", json={"settings": {"cats": 99}})
        assert resp.status_code == 422
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)


@pytest.mark.asyncio
async def test_settings_household_bool_rejected(client: AsyncClient, db_pool) -> None:
    hunt_id = await _seed_hunt(db_pool, _FULL_SETTINGS)
    try:
        resp = await client.patch(
            f"/v1/hunts/{hunt_id}/settings", json={"settings": {"cats": True}}
        )
        assert resp.status_code == 422
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)


@pytest.mark.asyncio
async def test_settings_cats_change_bumps_version_and_rescore(client: AsyncClient, db_pool) -> None:
    hunt_id = await _seed_hunt(db_pool, _FULL_SETTINGS)
    try:
        resp = await client.patch(f"/v1/hunts/{hunt_id}/settings", json={"settings": {"cats": 2}})
        assert resp.status_code == 200
        version = await db_pool.fetchval("select rubric_version from hunts where id = $1", hunt_id)
        assert version == 1
        rescore = await db_pool.fetchval(
            "select count(*) from jobs where type = 'rescore' and payload->>'hunt_id' = $1",
            hunt_id,
        )
        assert rescore == 1
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)


@pytest.mark.asyncio
async def test_settings_occupants_change_no_rescore(client: AsyncClient, db_pool) -> None:
    hunt_id = await _seed_hunt(db_pool, _FULL_SETTINGS)
    try:
        resp = await client.patch(
            f"/v1/hunts/{hunt_id}/settings", json={"settings": {"occupants": 4}}
        )
        assert resp.status_code == 200
        version = await db_pool.fetchval("select rubric_version from hunts where id = $1", hunt_id)
        assert version == 0
        rescore = await db_pool.fetchval(
            "select count(*) from jobs where type = 'rescore' and payload->>'hunt_id' = $1",
            hunt_id,
        )
        assert rescore == 0
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)


@pytest.mark.asyncio
async def test_settings_source_policy_change_no_rescore(client: AsyncClient, db_pool) -> None:
    hunt_id = uuid4()
    settings = {
        "default_source_policy": "tiers_1_2_3",
        "cost_estimate_mode": "conservative",
        "min_confidence": "medium",
        "proximity_mode": "driving",
    }
    await db_pool.execute(
        """
        insert into hunts (id, name, owner_id, settings, rubric_version)
        values ($1, 'S', $2, $3::jsonb, 0)
        """,
        hunt_id,
        FAKE_USER.id,
        json.dumps(settings),
    )
    try:
        resp = await client.patch(
            f"/v1/hunts/{hunt_id}/settings",
            json={"settings": {"default_source_policy": "tier_1"}},
        )
        assert resp.status_code == 200
        version = await db_pool.fetchval("select rubric_version from hunts where id = $1", hunt_id)
        assert version == 0
        rescore = await db_pool.fetchval(
            "select count(*) from jobs where type = 'rescore' and payload->>'hunt_id' = $1",
            str(hunt_id),
        )
        assert rescore == 0
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)
