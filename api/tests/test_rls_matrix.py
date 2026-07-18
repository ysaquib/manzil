"""P2-3 permission matrix at both the RLS boundary and API mirror."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

import asyncpg
import pytest
from httpx import AsyncClient
from postgrest.exceptions import APIError

Actor = Literal["owner", "curator", "member", "outsider"]


@dataclass(frozen=True)
class MatrixCase:
    actor: Actor
    action: str
    target: str
    allowed: bool


READ_MATRIX = [
    MatrixCase("owner", "read_hunt", "hunt", True),
    MatrixCase("curator", "read_hunt", "hunt", True),
    MatrixCase("member", "read_hunt", "hunt", True),
    MatrixCase("outsider", "read_hunt", "hunt", False),
]

PIN_MATRIX = [
    MatrixCase("owner", "patch_pins", "owner", True),
    MatrixCase("curator", "patch_pins", "owner", True),
    MatrixCase("member", "patch_pins", "member", True),
    MatrixCase("member", "patch_pins", "owner", False),
]

API_MUTATION_MATRIX = [
    MatrixCase("owner", "patch_hunt", "hunt", True),
    MatrixCase("curator", "patch_hunt", "hunt", False),
    MatrixCase("member", "patch_hunt", "hunt", False),
    MatrixCase("owner", "put_rubric", "hunt", True),
    MatrixCase("curator", "put_rubric", "hunt", False),
    MatrixCase("member", "put_rubric", "hunt", False),
    MatrixCase("owner", "override", "owner", True),
    MatrixCase("curator", "override", "owner", True),
    MatrixCase("member", "override", "member", True),
    MatrixCase("member", "override", "owner", False),
    MatrixCase("owner", "fee", "owner", True),
    MatrixCase("curator", "fee", "owner", True),
    MatrixCase("member", "fee", "member", True),
    MatrixCase("member", "fee", "owner", False),
    MatrixCase("owner", "delete_listing", "owner", True),
    MatrixCase("curator", "delete_listing", "owner", False),
    MatrixCase("member", "delete_listing", "member", False),
]


def _identity(seeded_users, actor: Actor):  # type: ignore[no-untyped-def]
    return seeded_users[actor]


@pytest.mark.parametrize("case", READ_MATRIX, ids=lambda c: c.actor)
def test_rls_hunt_visibility(case: MatrixCase, collab_hunt, seeded_users) -> None:
    rows = (
        _identity(seeded_users, case.actor)
        .supabase.table("hunts")
        .select("id")
        .eq("id", collab_hunt["hunt_id"])
        .execute()
        .data
        or []
    )
    assert bool(rows) is case.allowed


def test_rls_rejects_nonexistent_unit_group_collaboration(collab_hunt, seeded_users) -> None:
    listing_id = collab_hunt["member_listing_id"]
    member = seeded_users["member"]
    with pytest.raises(APIError):
        member.supabase.table("ratings").insert(
            {
                "hunt_listing_id": listing_id,
                "unit_group_key": "9-9",
                "user_id": member.user_id,
                "rating": 5,
            }
        ).execute()
    with pytest.raises(APIError):
        member.supabase.table("comments").insert(
            {
                "hunt_listing_id": listing_id,
                "unit_group_key": "9-9",
                "user_id": member.user_id,
                "body": "Impossible group",
            }
        ).execute()


def test_rls_unit_group_curation_requires_curator(collab_hunt, seeded_users) -> None:
    row = {
        "hunt_listing_id": collab_hunt["member_listing_id"],
        "unit_group_key": "2-1",
        "interest_status": "interested",
        "visited": True,
    }
    with pytest.raises(APIError):
        seeded_users["member"].supabase.table("listing_unit_group_states").insert(
            {**row, "updated_by": seeded_users["member"].user_id}
        ).execute()
    response = (
        seeded_users["curator"]
        .supabase.table("listing_unit_group_states")
        .insert({**row, "updated_by": seeded_users["curator"].user_id})
        .execute()
    )
    assert response.data[0]["interest_status"] == "interested"


@pytest.mark.asyncio
@pytest.mark.parametrize("case", READ_MATRIX, ids=lambda c: c.actor)
async def test_api_hunt_visibility(
    case: MatrixCase,
    collab_hunt,
    as_owner: AsyncClient,
    as_curator: AsyncClient,
    as_member: AsyncClient,
    as_outsider: AsyncClient,
) -> None:
    clients = {
        "owner": as_owner,
        "curator": as_curator,
        "member": as_member,
        "outsider": as_outsider,
    }
    response = await clients[case.actor].get(f"/v1/hunts/{collab_hunt['hunt_id']}")
    assert response.status_code == (200 if case.allowed else 404)


@pytest.mark.parametrize("case", PIN_MATRIX, ids=lambda c: f"{c.actor}-{c.target}")
def test_rls_pin_matrix(case: MatrixCase, collab_hunt, seeded_users) -> None:
    listing_id = collab_hunt[f"{case.target}_listing_id"]
    response = (
        _identity(seeded_users, case.actor)
        .supabase.table("hunt_listings")
        .update({"pins": {"test": str(uuid4())}})
        .eq("id", listing_id)
        .execute()
    )
    assert bool(response.data) is case.allowed


@pytest.mark.asyncio
@pytest.mark.parametrize("case", PIN_MATRIX, ids=lambda c: f"{c.actor}-{c.target}")
async def test_api_pin_matrix(
    case: MatrixCase,
    collab_hunt,
    as_owner: AsyncClient,
    as_curator: AsyncClient,
    as_member: AsyncClient,
) -> None:
    clients = {"owner": as_owner, "curator": as_curator, "member": as_member}
    listing_id = collab_hunt[f"{case.target}_listing_id"]
    response = await clients[case.actor].patch(f"/v1/listings/{listing_id}/pins", json={"pins": {}})
    assert response.status_code == (200 if case.allowed else 403)
    if not case.allowed:
        assert response.json()["code"] == "insufficient_role"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case", API_MUTATION_MATRIX, ids=lambda c: f"{c.actor}-{c.action}-{c.target}"
)
async def test_api_mutation_matrix(
    case: MatrixCase,
    collab_hunt,
    as_owner: AsyncClient,
    as_curator: AsyncClient,
    as_member: AsyncClient,
) -> None:
    clients = {"owner": as_owner, "curator": as_curator, "member": as_member}
    client = clients[case.actor]
    listing_id = collab_hunt.get(f"{case.target}_listing_id")
    if case.action == "patch_hunt":
        response = await client.patch(
            f"/v1/hunts/{collab_hunt['hunt_id']}", json={"name": "Authorized edit"}
        )
    elif case.action == "put_rubric":
        response = await client.put(
            f"/v1/hunts/{collab_hunt['hunt_id']}/rubric", json={"criteria": []}
        )
    elif case.action == "override":
        response = await client.post(
            f"/v1/listings/{listing_id}/overrides",
            json={"criterion_key": "beds", "value": 2},
        )
    elif case.action == "fee":
        response = await client.put(
            f"/v1/listings/{listing_id}/fees/parking",
            json={"amount": 25, "value_state": "manual"},
        )
    elif case.action == "delete_listing":
        response = await client.delete(f"/v1/listings/{listing_id}")
    else:  # pragma: no cover - matrix vocabulary is closed above
        raise AssertionError(case.action)

    expected = 204 if case.allowed and case.action == "delete_listing" else 200
    if case.action == "override" and case.allowed:
        expected = 201
    assert response.status_code == (expected if case.allowed else 403)
    if not case.allowed:
        assert response.json()["code"] == "insufficient_role"


def test_rls_member_cannot_self_promote(collab_hunt, seeded_users) -> None:
    with pytest.raises(APIError):
        (
            seeded_users["member"]
            .supabase.table("hunt_members")
            .update({"role": "curator"})
            .eq("hunt_id", collab_hunt["hunt_id"])
            .eq("user_id", seeded_users["member"].user_id)
            .execute()
        )


def test_rls_owner_row_cannot_be_deleted(collab_hunt, seeded_users) -> None:
    response = (
        seeded_users["owner"]
        .supabase.table("hunt_members")
        .delete()
        .eq("hunt_id", collab_hunt["hunt_id"])
        .eq("user_id", seeded_users["owner"].user_id)
        .execute()
    )
    assert response.data == []


@pytest.mark.asyncio
async def test_one_owner_unique_index_is_backstop(collab_hunt, db_pool, seeded_users) -> None:
    with pytest.raises(asyncpg.UniqueViolationError):
        await db_pool.execute(
            "insert into hunt_members (hunt_id, user_id, role) values ($1, $2, 'owner')",
            collab_hunt["hunt_id"],
            seeded_users["outsider"].user_id,
        )


@pytest.mark.asyncio
async def test_custom_extraction_is_hunt_scoped(db_pool, seeded_users, collab_hunt) -> None:
    other_hunt = await db_pool.fetchval(
        "insert into hunts (name, owner_id) values ('Other', $1) returning id",
        seeded_users["outsider"].user_id,
    )
    property_id = await db_pool.fetchval(
        """insert into properties (name, canonical_address)
           values ('Other', '3 Test St') returning id"""
    )
    extraction_id = await db_pool.fetchval(
        """insert into extractions
           (property_id, hunt_id, criterion_key, value, confidence, model)
           values ($1, $2, 'private_custom', 'true'::jsonb, 'high', 'fixture') returning id""",
        property_id,
        other_hunt,
    )
    try:
        member_rows = (
            seeded_users["member"]
            .supabase.table("extractions")
            .select("id")
            .eq("id", str(extraction_id))
            .execute()
            .data
            or []
        )
        outsider_rows = (
            seeded_users["outsider"]
            .supabase.table("extractions")
            .select("id")
            .eq("id", str(extraction_id))
            .execute()
            .data
            or []
        )
        assert member_rows == []
        assert len(outsider_rows) == 1
    finally:
        await db_pool.execute("delete from hunts where id = $1", other_hunt)
        await db_pool.execute("delete from properties where id = $1", property_id)


@pytest.mark.asyncio
async def test_job_own_vs_any_and_curator_checkpoint(
    db_pool,
    collab_hunt,
    seeded_users,
    as_curator: AsyncClient,
) -> None:
    queued_job = await db_pool.fetchval(
        """insert into jobs (hunt_id, hunt_listing_id, type, state)
           values ($1, $2, 'ingest', 'queued') returning id""",
        collab_hunt["hunt_id"],
        collab_hunt["owner_listing_id"],
    )
    prompt = {
        "kind": "confirm_value",
        "question": "Confirm?",
        "options": ["yes", "no"],
        "default": "yes",
    }
    waiting_payload = {
        "run_state": {
            "job_id": str(uuid4()),
            "job_type": "ingest",
            "url": "https://example.com",
            "status": "waiting_user",
            "checkpoint": prompt,
        }
    }
    waiting_job = await db_pool.fetchval(
        """insert into jobs (hunt_id, hunt_listing_id, type, state, payload)
           values ($1, $2, 'ingest', 'waiting_user', $3::jsonb) returning id""",
        collab_hunt["hunt_id"],
        collab_hunt["owner_listing_id"],
        json.dumps(waiting_payload),
    )
    try:
        raw_cancel = (
            seeded_users["member"]
            .supabase.table("jobs")
            .update({"state": "cancelled"})
            .eq("id", str(queued_job))
            .execute()
        )
        assert raw_cancel.data == []

        cancel = await as_curator.post(f"/v1/jobs/{queued_job}/cancel")
        assert cancel.status_code == 403
        assert cancel.json()["code"] == "not_job_owner"

        checkpoint = await as_curator.post(
            f"/v1/jobs/{waiting_job}/checkpoint",
            json={"answer": {"choice": "yes"}},
        )
        assert checkpoint.status_code == 200
        assert checkpoint.json()["state"] == "queued"
    finally:
        await db_pool.execute(
            "delete from jobs where id = any($1::uuid[])", [queued_job, waiting_job]
        )


@pytest.mark.asyncio
async def test_member_lists_membership_hunt(collab_hunt, as_member: AsyncClient) -> None:
    response = await as_member.get("/v1/hunts")
    assert response.status_code == 200
    assert collab_hunt["hunt_id"] in {row["id"] for row in response.json()}


@pytest.mark.asyncio
async def test_curator_remaining_stewardship_boundaries(
    collab_hunt,
    as_curator: AsyncClient,
    db_pool,
    seeded_users,
) -> None:
    """P2-9: Curator stewardship stops at Jobs, settings, and member roles."""
    failed_job = await db_pool.fetchval(
        """insert into jobs
           (hunt_id, hunt_listing_id, type, state, error, finished_at)
           values ($1, $2, 'ingest', 'failed', 'fixture', now()) returning id""",
        collab_hunt["hunt_id"],
        collab_hunt["owner_listing_id"],
    )
    retry = await as_curator.post(f"/v1/jobs/{failed_job}/retry")
    assert retry.status_code == 403
    assert retry.json()["code"] == "not_job_owner"

    settings = await as_curator.patch(
        f"/v1/hunts/{collab_hunt['hunt_id']}/settings",
        json={"settings": {"min_confidence": "low"}},
    )
    assert settings.status_code == 403
    assert settings.json()["code"] == "insufficient_role"

    role_change = await as_curator.patch(
        f"/v1/hunts/{collab_hunt['hunt_id']}/members/{seeded_users['member'].user_id}",
        json={"role": "curator"},
    )
    assert role_change.status_code == 403
    assert role_change.json()["code"] == "cannot_edit_member"
