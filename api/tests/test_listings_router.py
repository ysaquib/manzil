"""P1-7 listings router tests."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from api_helpers import FAKE_USER
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_listing_inserts_property_and_ingest_job(client: AsyncClient, db_pool) -> None:
    hunt_id = uuid4()
    await db_pool.execute(
        """
        insert into hunts (id, name, owner_id, settings)
        values ($1, 'L', $2, $3::jsonb)
        """,
        hunt_id,
        FAKE_USER.id,
        json.dumps({"default_source_policy": "tiers_1_2_3"}),
    )
    try:
        url = "https://maple-court.seed.example/floorplans"
        resp = await client.post(f"/v1/hunts/{hunt_id}/listings", json={"url": url})
        assert resp.status_code == 201
        listing_id = resp.json()["id"]
        job = await db_pool.fetchrow(
            "select type, state, payload from jobs where hunt_listing_id = $1",
            listing_id,
        )
        assert job is not None
        assert job["type"] == "ingest"
        assert job["state"] == "queued"
        payload = json.loads(job["payload"]) if isinstance(job["payload"], str) else job["payload"]
        assert payload["url"] == url
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)


@pytest.mark.asyncio
async def test_delete_listing_soft_archives(client: AsyncClient, db_pool) -> None:
    hunt_id, listing_id, property_id = uuid4(), uuid4(), uuid4()
    await db_pool.execute(
        "insert into hunts (id, name, owner_id) values ($1, 'L', $2)",
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
    job_id = await db_pool.fetchval(
        """
        insert into jobs (hunt_id, hunt_listing_id, type, state, payload)
        values ($1, $2, 'ingest', 'done', '{}'::jsonb) returning id
        """,
        hunt_id,
        listing_id,
    )
    try:
        resp = await client.delete(f"/v1/listings/{listing_id}")
        assert resp.status_code == 204
        status = await db_pool.fetchval(
            "select status from hunt_listings where id = $1", listing_id
        )
        assert status == "archived"
        job_exists = await db_pool.fetchval("select id from jobs where id = $1", job_id)
        assert job_exists is not None
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)


@pytest.mark.asyncio
async def test_patch_status_archives_and_restores(client: AsyncClient, db_pool) -> None:
    hunt_id, listing_id, property_id = uuid4(), uuid4(), uuid4()
    await db_pool.execute(
        "insert into hunts (id, name, owner_id) values ($1, 'L', $2)",
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
    try:
        resp = await client.patch(f"/v1/listings/{listing_id}/status", json={"status": "archived"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "archived"

        resp = await client.patch(f"/v1/listings/{listing_id}/status", json={"status": "active"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "active"
        status = await db_pool.fetchval(
            "select status from hunt_listings where id = $1", listing_id
        )
        assert status == "active"
    finally:
        await db_pool.execute("delete from hunts where id = $1", hunt_id)


@pytest.mark.asyncio
async def test_curator_updates_unit_group_state_and_member_cannot(
    collab_hunt, as_curator: AsyncClient, as_member: AsyncClient
) -> None:
    path = f"/v1/listings/{collab_hunt['member_listing_id']}/unit-groups/2-1/state"
    payload = {"interest_status": "applied", "visited": True}
    curator_response = await as_curator.patch(path, json=payload)
    assert curator_response.status_code == 200
    assert curator_response.json()["interest_status"] == "applied"
    assert curator_response.json()["visited"] is True

    member_response = await as_member.patch(path, json=payload)
    assert member_response.status_code == 403


@pytest.mark.asyncio
async def test_source_policy_relaxation_queues_discover_refresh_atomically(
    collab_hunt, as_owner: AsyncClient, db_pool
) -> None:
    listing_id = collab_hunt["member_listing_id"]
    hunt_id = collab_hunt["hunt_id"]
    submitted = f"https://example.com/listing/{uuid4()}"
    await db_pool.execute(
        """insert into jobs (hunt_id, hunt_listing_id, type, state, payload)
           values ($1, $2, 'ingest', 'done', $3::jsonb)""",
        hunt_id,
        listing_id,
        json.dumps({"url": submitted, "source_policy": "tiers_1_2_3"}),
    )
    # Tighten first: metadata changes, but no DISCOVER refresh is useful.
    tightened = await as_owner.patch(
        f"/v1/listings/{listing_id}/source-policy",
        json={"source_policy": "tier_1"},
    )
    assert tightened.status_code == 200
    assert tightened.json()["source_policy"] == "tier_1"
    refreshes = await db_pool.fetchval(
        "select count(*) from jobs where hunt_listing_id = $1 and type = 'refresh'",
        listing_id,
    )
    assert refreshes == 0

    # The official link is discovered under every non-trust policy, so enabling
    # only its future P3-6 fetch carve-out must not pay for a no-op DISCOVER.
    official_carveout = await as_owner.patch(
        f"/v1/listings/{listing_id}/source-policy",
        json={"source_policy": "tier_1_plus_official"},
    )
    assert official_carveout.status_code == 200
    refreshes = await db_pool.fetchval(
        "select count(*) from jobs where hunt_listing_id = $1 and type = 'refresh'",
        listing_id,
    )
    assert refreshes == 0

    relaxed = await as_owner.patch(
        f"/v1/listings/{listing_id}/source-policy",
        json={"source_policy": "tiers_1_2"},
    )
    assert relaxed.status_code == 200
    assert relaxed.json()["source_policy"] == "tiers_1_2"
    job = await db_pool.fetchrow(
        """select state, payload from jobs
           where hunt_listing_id = $1 and type = 'refresh'""",
        listing_id,
    )
    assert job is not None and job["state"] == "queued"
    payload = json.loads(job["payload"]) if isinstance(job["payload"], str) else job["payload"]
    assert payload == {
        "url": submitted,
        "scope": "discover",
        "hunt_id": hunt_id,
        "listing_id": listing_id,
        "source_policy": "tiers_1_2",
    }


@pytest.mark.asyncio
async def test_source_policy_edit_is_owner_or_submitter_only(
    collab_hunt, as_curator: AsyncClient, as_member: AsyncClient, db_pool
) -> None:
    owner_listing = collab_hunt["owner_listing_id"]
    member_listing = collab_hunt["member_listing_id"]
    forbidden = await as_curator.patch(
        f"/v1/listings/{member_listing}/source-policy",
        json={"source_policy": "trust_link"},
    )
    assert forbidden.status_code == 403

    own = await as_member.patch(
        f"/v1/listings/{member_listing}/source-policy",
        json={"source_policy": "trust_link"},
    )
    assert own.status_code == 200
    assert own.json()["single_source_reason"] == "trust_link"

    other = await as_member.patch(
        f"/v1/listings/{owner_listing}/source-policy",
        json={"source_policy": "trust_link"},
    )
    assert other.status_code == 403


@pytest.mark.asyncio
async def test_listing_refresh_enqueues_and_coalesces_class_job(
    collab_hunt, as_owner: AsyncClient, db_pool
) -> None:
    listing_id = collab_hunt["owner_listing_id"]
    property_id = await db_pool.fetchval(
        "select property_id from hunt_listings where id = $1", listing_id
    )
    source_id = await db_pool.fetchval(
        """
        insert into property_sources
            (property_id, url, site_domain, cleaned_text_hash, last_success_at)
        values ($1, $2, 'refresh.test', 'old', now())
        returning id
        """,
        property_id,
        f"https://refresh.test/{listing_id}",
    )
    await db_pool.execute(
        "update hunt_listings set submitted_source_id = $2 where id = $1",
        listing_id,
        source_id,
    )

    first = await as_owner.post(
        f"/v1/listings/{listing_id}/refresh",
        json={"fields": ["pricing", "pricing"]},
    )
    assert first.status_code == 202
    assert first.json()["type"] == "refresh"
    second = await as_owner.post(
        f"/v1/listings/{listing_id}/refresh",
        json={"fields": ["pricing"]},
    )
    assert second.status_code == 202
    assert second.json()["id"] == first.json()["id"]
    payload = await db_pool.fetchval("select payload from jobs where id = $1", first.json()["id"])
    if isinstance(payload, str):
        payload = json.loads(payload)
    assert payload["scope"] == "classes"
    assert payload["fields"] == ["pricing"]

    combined = await as_owner.post(
        f"/v1/listings/{listing_id}/refresh",
        json={"fields": ["listing_details", "pricing"]},
    )
    reordered = await as_owner.post(
        f"/v1/listings/{listing_id}/refresh",
        json={"fields": ["pricing", "listing_details"]},
    )
    assert reordered.json()["id"] == combined.json()["id"]


@pytest.mark.asyncio
async def test_listing_refresh_rejects_empty_fields(collab_hunt, as_owner: AsyncClient) -> None:
    response = await as_owner.post(
        f"/v1/listings/{collab_hunt['owner_listing_id']}/refresh",
        json={"fields": []},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_curator_can_refresh_hunt_but_not_another_submitters_listing(
    collab_hunt, as_curator: AsyncClient, db_pool
) -> None:
    listing_ids = [
        collab_hunt["member_listing_id"],
        collab_hunt["owner_listing_id"],
    ]
    await db_pool.execute(
        """
        update property_sources ps
        set last_success_at = now()
        from hunt_listings hl
        where hl.property_id = ps.property_id
          and hl.id = any($1::uuid[])
        """,
        listing_ids,
    )
    await db_pool.execute(
        """
        update hunt_listings hl
        set submitted_source_id = ps.id
        from property_sources ps
        where ps.property_id = hl.property_id
          and hl.id = any($1::uuid[])
        """,
        listing_ids,
    )

    direct = await as_curator.post(
        f"/v1/listings/{collab_hunt['owner_listing_id']}/refresh",
        json={"fields": ["pricing"]},
    )
    assert direct.status_code == 403

    response = await as_curator.post(
        f"/v1/hunts/{collab_hunt['hunt_id']}/refresh",
        json={"fields": ["pricing"]},
    )
    assert response.status_code == 202
    assert len(response.json()) == 2
    queued = await db_pool.fetchval(
        """
        select count(*) from jobs
        where hunt_id = $1 and type = 'refresh' and state = 'queued'
        """,
        collab_hunt["hunt_id"],
    )
    assert queued == 2
