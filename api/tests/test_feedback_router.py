"""Feedback submission + its insert-only RLS posture (P3-16, DESIGN §20 v3.27)."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from postgrest.exceptions import APIError


@pytest.fixture(autouse=True)
async def clean_feedback(db_pool):
    """Feedback rows accumulate against a per-hour cap, so each test starts empty."""
    await db_pool.execute("delete from feedback")
    yield
    await db_pool.execute("delete from feedback")


async def test_submit_feedback_records_caller_and_context(
    as_owner: AsyncClient, db_pool, seeded_users, collab_hunt
) -> None:
    response = await as_owner.post(
        "/v1/feedback",
        json={
            "category": "bug",
            "body": "  All-in cost differs between the drawer and the table.  ",
            "route": "/h/248f1b46?listing=lst_8f21",
            "hunt_id": str(collab_hunt["hunt_id"]),
            "app_version": "v3.27",
        },
    )
    assert response.status_code == 201
    body = response.json()

    row = await db_pool.fetchrow("select * from feedback where id = $1", UUID(body["id"]))
    assert row is not None
    # Identity comes from the token, never the body.
    assert str(row["user_id"]) == seeded_users["owner"].user_id
    assert row["category"] == "bug"
    assert row["body"] == "All-in cost differs between the drawer and the table."
    assert row["route"] == "/h/248f1b46?listing=lst_8f21"
    assert str(row["hunt_id"]) == str(collab_hunt["hunt_id"])
    assert row["app_version"].startswith("frontend v3.27 · api ")
    # Captured from the request, not the payload.
    assert row["user_agent"] is not None


async def test_submit_feedback_without_a_hunt(as_owner: AsyncClient, db_pool) -> None:
    response = await as_owner.post(
        "/v1/feedback",
        json={"category": "feature", "body": "Let me sort by commute time."},
    )
    assert response.status_code == 201
    row = await db_pool.fetchrow(
        "select hunt_id, route from feedback where id = $1", UUID(response.json()["id"])
    )
    assert row["hunt_id"] is None
    assert row["route"] is None


async def test_submit_feedback_rejects_unknown_category(as_owner: AsyncClient) -> None:
    response = await as_owner.post("/v1/feedback", json={"category": "praise", "body": "Nice app"})
    assert response.status_code == 422


async def test_submit_feedback_rejects_blank_and_oversized_body(as_owner: AsyncClient) -> None:
    blank = await as_owner.post("/v1/feedback", json={"category": "other", "body": "   "})
    assert blank.status_code == 422
    huge = await as_owner.post("/v1/feedback", json={"category": "other", "body": "x" * 4001})
    assert huge.status_code == 422


async def test_submit_feedback_rejects_absolute_route(as_owner: AsyncClient) -> None:
    """A report may say where in *this* app it came from, not point anywhere."""
    for bad in ("https://evil.example/h/1", "//evil.example/h/1", "h/1"):
        response = await as_owner.post(
            "/v1/feedback",
            json={"category": "bug", "body": "Something broke", "route": bad},
        )
        assert response.status_code == 422, bad


async def test_submit_feedback_rejects_a_hunt_the_caller_cannot_see(
    as_outsider: AsyncClient, collab_hunt
) -> None:
    response = await as_outsider.post(
        "/v1/feedback",
        json={
            "category": "bug",
            "body": "Tagging a hunt I am not in",
            "hunt_id": str(collab_hunt["hunt_id"]),
        },
    )
    assert response.status_code == 403
    assert response.json()["code"] == "hunt_not_visible"


async def test_feedback_rate_limit_returns_429(as_owner: AsyncClient) -> None:
    for index in range(10):
        ok = await as_owner.post(
            "/v1/feedback", json={"category": "other", "body": f"Report {index}"}
        )
        assert ok.status_code == 201, index

    limited = await as_owner.post(
        "/v1/feedback", json={"category": "other", "body": "One too many"}
    )
    assert limited.status_code == 429
    assert limited.json()["code"] == "feedback_rate_limited"


async def test_feedback_is_never_readable_by_its_own_submitter(
    as_owner: AsyncClient, seeded_users
) -> None:
    """The defining property of this table: insert-only, with no SELECT policy
    for anyone — including the person who wrote the row."""
    created = await as_owner.post(
        "/v1/feedback", json={"category": "bug", "body": "Only I wrote this"}
    )
    assert created.status_code == 201

    owner_client = seeded_users["owner"].supabase
    rows = owner_client.table("feedback").select("*").execute().data
    assert rows == []


async def test_feedback_cannot_be_written_on_behalf_of_someone_else(
    seeded_users, collab_hunt
) -> None:
    """Direct PostgREST insert, bypassing the API: RLS still pins user_id."""
    curator_client = seeded_users["curator"].supabase
    with pytest.raises(APIError):
        curator_client.table("feedback").insert(
            {
                "id": str(uuid4()),
                "user_id": seeded_users["owner"].user_id,
                "category": "bug",
                "body": "Attributed to the owner",
            },
            returning="minimal",
        ).execute()


async def test_feedback_rows_cannot_be_updated_or_deleted(
    as_owner: AsyncClient, db_pool, seeded_users
) -> None:
    created = await as_owner.post(
        "/v1/feedback", json={"category": "bug", "body": "Immutable once sent"}
    )
    feedback_id = created.json()["id"]
    owner_client = seeded_users["owner"].supabase

    # With no UPDATE or DELETE policy, the caller matches no rows — PostgREST
    # reports success over an empty set rather than erroring. What matters is
    # that the stored row is untouched by either attempt.
    owner_client.table("feedback").update({"body": "edited"}, returning="minimal").eq(
        "id", feedback_id
    ).execute()
    owner_client.table("feedback").delete(returning="minimal").eq("id", feedback_id).execute()

    still_there = await db_pool.fetchval(
        "select body from feedback where id = $1", UUID(feedback_id)
    )
    assert still_there == "Immutable once sent"
