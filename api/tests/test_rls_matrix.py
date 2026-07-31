"""P2-3 permission matrix at both the RLS boundary and API mirror."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
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
    MatrixCase("owner", "utility", "owner", True),
    MatrixCase("curator", "utility", "owner", True),
    MatrixCase("member", "utility", "member", True),
    MatrixCase("member", "utility", "owner", False),
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


@pytest.mark.asyncio
async def test_rls_rejects_cross_property_floor_plan_override(
    collab_hunt, db_pool, seeded_users
) -> None:
    foreign_plan_id = await db_pool.fetchval(
        """
        select fp.id
        from floor_plans fp
        join hunt_listings hl on hl.property_id = fp.property_id
        where hl.id = $1
        limit 1
        """,
        collab_hunt["member_listing_id"],
    )
    with pytest.raises(APIError):
        seeded_users["owner"].supabase.table("overrides").insert(
            {
                "hunt_listing_id": collab_hunt["owner_listing_id"],
                "criterion_key": "dishwasher",
                "target_scope": "floor_plan",
                "floor_plan_id": str(foreign_plan_id),
                "applicability": "specific_floor_plans",
                "value": True,
                "user_id": seeded_users["owner"].user_id,
            }
        ).execute()


VISIT_READ_MATRIX = [
    MatrixCase("owner", "read_visit", "visit", True),
    MatrixCase("curator", "read_visit", "visit", True),
    MatrixCase("member", "read_visit", "visit", True),
    MatrixCase("outsider", "read_visit", "visit", False),
]


def _seed_visit(seeded_users, collab_hunt, actor: Actor = "member") -> str:
    identity = _identity(seeded_users, actor)
    return (
        identity.supabase.table("visits")
        .insert(
            {
                "hunt_id": collab_hunt["hunt_id"],
                "property_id": collab_hunt["owner_property_id"],
                "created_by": identity.user_id,
                "template_version": 1,
            }
        )
        .execute()
        .data[0]["id"]
    )


@pytest.mark.parametrize("case", VISIT_READ_MATRIX, ids=lambda c: c.actor)
def test_rls_visit_visibility(case: MatrixCase, collab_hunt, seeded_users) -> None:
    """VC-1: every member of the owning Hunt reads a Visit; nobody else does."""
    visit_id = _seed_visit(seeded_users, collab_hunt)
    rows = (
        _identity(seeded_users, case.actor)
        .supabase.table("visits")
        .select("id")
        .eq("id", visit_id)
        .execute()
        .data
        or []
    )
    assert bool(rows) is case.allowed


def test_rls_visit_units_inherit_their_visit_visibility(collab_hunt, seeded_users) -> None:
    visit_id = _seed_visit(seeded_users, collab_hunt)
    member = seeded_users["member"]
    member.supabase.table("visit_units").insert(
        {
            "visit_id": visit_id,
            "label": "4B",
            "beds": 2,
            "baths": 2,
            "created_by": member.user_id,
        }
    ).execute()
    assert (
        seeded_users["curator"]
        .supabase.table("visit_units")
        .select("id")
        .eq("visit_id", visit_id)
        .execute()
        .data
    )
    assert not (
        seeded_users["outsider"]
        .supabase.table("visit_units")
        .select("id")
        .eq("visit_id", visit_id)
        .execute()
        .data
    )


def test_rls_outsider_cannot_create_a_visit(collab_hunt, seeded_users) -> None:
    outsider = seeded_users["outsider"]
    with pytest.raises(APIError):
        outsider.supabase.table("visits").insert(
            {
                "hunt_id": collab_hunt["hunt_id"],
                "property_id": collab_hunt["owner_property_id"],
                "created_by": outsider.user_id,
                "template_version": 1,
            }
        ).execute()


def test_rls_visit_cannot_be_created_under_another_users_identity(
    collab_hunt, seeded_users
) -> None:
    """`created_by` is pinned to `auth.uid()`, so a member cannot forge authorship
    and thereby hand themselves the creator-only cancel right."""
    member = seeded_users["member"]
    with pytest.raises(APIError):
        member.supabase.table("visits").insert(
            {
                "hunt_id": collab_hunt["hunt_id"],
                "property_id": collab_hunt["owner_property_id"],
                "created_by": seeded_users["owner"].user_id,
                "template_version": 1,
            }
        ).execute()


@pytest.mark.asyncio
async def test_rls_visit_requires_a_property_in_this_hunt(
    collab_hunt, db_pool, seeded_users
) -> None:
    foreign_property = await db_pool.fetchval(
        "insert into properties (name, canonical_address) "
        "values ('Foreign', '77 Away') returning id"
    )
    try:
        member = seeded_users["member"]
        with pytest.raises(APIError):
            member.supabase.table("visits").insert(
                {
                    "hunt_id": collab_hunt["hunt_id"],
                    "property_id": str(foreign_property),
                    "created_by": member.user_id,
                    "template_version": 1,
                }
            ).execute()
    finally:
        await db_pool.execute("delete from properties where id = $1", foreign_property)


def test_rls_rejects_cross_property_visit_unit_floor_plan(collab_hunt, seeded_users) -> None:
    """A Visit Unit may only point at a Floor Plan of its own Visit's Property —
    the same guard the cross-Property Override already carries."""
    visit_id = _seed_visit(seeded_users, collab_hunt)
    member = seeded_users["member"]
    with pytest.raises(APIError):
        member.supabase.table("visit_units").insert(
            {
                "visit_id": visit_id,
                "label": "impossible",
                "floor_plan_id": collab_hunt["member_plan_id"],  # belongs to the other Property
                "beds": 2,
                "baths": 2,
                "created_by": member.user_id,
            }
        ).execute()


def test_rls_cancel_narrows_to_creator_or_owner_at_the_database(collab_hunt, seeded_users) -> None:
    """The narrowing lives in a trigger, not a policy, because it is a statement
    about *which column changed*. Assert it holds against a direct write, not
    only through the API."""
    visit_id = _seed_visit(seeded_users, collab_hunt, actor="member")
    stamp = "2026-08-01T12:00:00+00:00"

    with pytest.raises(APIError):
        seeded_users["curator"].supabase.table("visits").update({"cancelled_at": stamp}).eq(
            "id", visit_id
        ).execute()

    # A Curator may still start the tour: only cancellation is narrowed.
    started = (
        seeded_users["curator"]
        .supabase.table("visits")
        .update({"started_at": stamp})
        .eq("id", visit_id)
        .execute()
        .data
    )
    assert started and started[0]["started_at"] is not None

    owner_cancel = (
        seeded_users["owner"]
        .supabase.table("visits")
        .update({"cancelled_at": stamp})
        .eq("id", visit_id)
        .execute()
        .data
    )
    assert owner_cancel and owner_cancel[0]["cancelled_at"] is not None


def test_rls_visit_identity_columns_are_immutable(collab_hunt, seeded_users, db_pool) -> None:
    visit_id = _seed_visit(seeded_users, collab_hunt)
    member = seeded_users["member"]
    with pytest.raises(APIError):
        member.supabase.table("visits").update(
            {"property_id": collab_hunt["member_property_id"]}
        ).eq("id", visit_id).execute()
    with pytest.raises(APIError):
        member.supabase.table("visits").update({"template_version": 99}).eq(
            "id", visit_id
        ).execute()


def test_rls_visit_delete_narrows_to_creator_or_owner(collab_hunt, seeded_users) -> None:
    visit_id = _seed_visit(seeded_users, collab_hunt, actor="member")
    # A Curator's delete matches no row rather than raising: RLS filters it out.
    seeded_users["curator"].supabase.table("visits").delete().eq("id", visit_id).execute()
    assert (
        seeded_users["member"]
        .supabase.table("visits")
        .select("id")
        .eq("id", visit_id)
        .execute()
        .data
    )
    seeded_users["member"].supabase.table("visits").delete().eq("id", visit_id).execute()
    assert not (
        seeded_users["member"]
        .supabase.table("visits")
        .select("id")
        .eq("id", visit_id)
        .execute()
        .data
    )


def test_rls_template_is_readable_but_never_writable(seeded_users) -> None:
    """Global reference data: any authenticated user reads it, no client writes it."""
    member = seeded_users["member"]
    assert member.supabase.table("visit_template_items").select("key").limit(1).execute().data
    assert (
        seeded_users["outsider"]
        .supabase.table("visit_template_items")
        .select("key")
        .limit(1)
        .execute()
        .data
    )
    with pytest.raises(APIError):
        member.supabase.table("visit_template_items").insert(
            {
                "key": "forged",
                "version": 1,
                "section_key": "kitchen",
                "display_order": 9999,
                "tier": "quick",
                "kind": "check",
                "scope": "unit",
                "label": "Forged item",
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
    elif case.action == "utility":
        response = await client.put(
            f"/v1/listings/{listing_id}/utilities/electric",
            json={"included": False, "monthly_amount": 80},
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
           (property_id, hunt_id, criterion_key, record_kind, origin_key,
            target_scope, value, confidence, model, resolution_rule)
           values ($1, $2, 'private_custom', 'resolved', 'fixture:private_custom',
                   'property', 'true'::jsonb, 'high', 'fixture', 'fixture')
           returning id""",
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
    as_member: AsyncClient,
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
    auto_job_id = uuid4()
    auto_snapshot = {
        **waiting_payload["run_state"],
        "job_id": str(auto_job_id),
        "cursor": 4,
    }
    auto_payload = {
        "url": "https://example.com",
        "run_state": {**auto_snapshot, "status": "done", "checkpoint": None},
        "auto_resolved_checkpoint": {
            "prompt": prompt,
            "answer": {"choice": "yes", "context_ref": None},
            "resolved_at": datetime.now(UTC).isoformat(),
            "snapshot": auto_snapshot,
        },
    }
    auto_job = await db_pool.fetchval(
        """insert into jobs
               (id, hunt_id, hunt_listing_id, type, state, payload, finished_at)
           values ($1, $2, $3, 'ingest', 'done', $4::jsonb, now()) returning id""",
        auto_job_id,
        collab_hunt["hunt_id"],
        collab_hunt["owner_listing_id"],
        json.dumps(auto_payload),
    )
    await db_pool.execute(
        """
        insert into job_events (job_id, stage, event)
        values ($1, 'VERIFY', 'checkpoint_auto_resolved')
        """,
        auto_job,
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

        denied_correction = await as_member.post(
            f"/v1/jobs/{auto_job}/checkpoint",
            json={"answer": {"choice": "no"}},
        )
        assert denied_correction.status_code == 403

        correction = await as_curator.post(
            f"/v1/jobs/{auto_job}/checkpoint",
            json={"answer": {"choice": "no"}},
        )
        assert correction.status_code == 200
        assert correction.json()["state"] == "queued"
        assert correction.json()["id"] != str(auto_job)
    finally:
        await db_pool.execute(
            "delete from jobs where id = any($1::uuid[])",
            [queued_job, waiting_job, auto_job],
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
