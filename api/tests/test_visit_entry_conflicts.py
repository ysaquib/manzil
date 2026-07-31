"""Offline answer forks, surfaced rather than resolved (VC-6, DESIGN §9.7).

The `visit_entry_conflicts` view decides what counts as a conflict, so these
tests are about its definition rather than any route: a fork is two writes
claiming the same parent **and disagreeing**, it stays open until something
descends from a branch, and nothing is ever discarded along the way.

Resolution deliberately has no endpoint of its own — it is an ordinary answer
whose `prev_entry_id` is the chosen branch, which is what append-only buys.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

PROPERTY_CHECK = "prep_reviews"
UNIT_FACT = "kitchen_stove_type"


async def _visit(client: AsyncClient, collab_hunt) -> dict:  # type: ignore[no-untyped-def]
    created = await client.post(
        f"/v1/hunts/{collab_hunt['hunt_id']}/visits",
        json={
            "property_id": collab_hunt["owner_property_id"],
            "units": [{"label": "4B", "beds": 2, "baths": 2}],
        },
    )
    assert created.status_code == 201, created.text
    return created.json()


async def _save(client: AsyncClient, visit_id: str, entries: list[dict]):  # type: ignore[no-untyped-def]
    response = await client.put(f"/v1/visits/{visit_id}/entries", json={"entries": entries})
    assert response.status_code == 200, response.text
    return response.json()


async def _fork(db_pool, visit_id: str, item_key: str, parent: str, value: str, author: str) -> str:
    """Write a branch directly: an offline client's queued write, arriving late."""
    return await db_pool.fetchval(
        "insert into visit_entries "
        "(visit_id, item_key, is_custom, author_user_id, value, prev_entry_id) "
        "values ($1, $2, false, $3, $4::jsonb, $5) returning id",
        visit_id,
        item_key,
        author,
        value,
        parent,
    )


async def _open_forks(db_pool, visit_id: str) -> list:
    return await db_pool.fetch(
        "select id, value, author_user_id, fork_parent_id from visit_entry_conflicts "
        "where visit_id = $1 order by value",
        visit_id,
    )


@pytest.mark.asyncio
async def test_two_writes_that_disagree_about_the_same_parent_are_a_conflict(
    collab_hunt, as_member: AsyncClient, db_pool, seeded_users
) -> None:
    visit = await _visit(as_member, collab_hunt)
    saved = await _save(as_member, visit["id"], [{"item_key": PROPERTY_CHECK, "value": "ok"}])
    parent = saved[0]["id"]

    await _fork(
        db_pool, visit["id"], PROPERTY_CHECK, parent, '"problem"', seeded_users["owner"].user_id
    )
    await _fork(
        db_pool, visit["id"], PROPERTY_CHECK, parent, '"ok"', seeded_users["member"].user_id
    )

    rows = await _open_forks(db_pool, visit["id"])
    assert len(rows) == 2
    assert {row["value"] for row in rows} == {'"problem"', '"ok"'}


@pytest.mark.asyncio
async def test_writes_that_agree_are_not_a_conflict(
    collab_hunt, as_member: AsyncClient, db_pool, seeded_users
) -> None:
    """Two people reaching the same answer have nothing to decide.

    This is also what makes the view immune to a duplicate replay: a queued
    write that flushes as the tab navigates can be restored and sent twice,
    carrying the same parent. Prompting for that would teach people to dismiss
    the picker.
    """
    visit = await _visit(as_member, collab_hunt)
    saved = await _save(as_member, visit["id"], [{"item_key": PROPERTY_CHECK, "value": "ok"}])
    parent = saved[0]["id"]

    await _fork(
        db_pool, visit["id"], PROPERTY_CHECK, parent, '"problem"', seeded_users["owner"].user_id
    )
    await _fork(
        db_pool, visit["id"], PROPERTY_CHECK, parent, '"problem"', seeded_users["member"].user_id
    )

    assert await _open_forks(db_pool, visit["id"]) == []


@pytest.mark.asyncio
async def test_a_repeated_answer_is_not_offered_as_its_own_option(
    collab_hunt, as_member: AsyncClient, db_pool, seeded_users
) -> None:
    visit = await _visit(as_member, collab_hunt)
    saved = await _save(as_member, visit["id"], [{"item_key": PROPERTY_CHECK, "value": "ok"}])
    parent = saved[0]["id"]

    await _fork(
        db_pool, visit["id"], PROPERTY_CHECK, parent, '"problem"', seeded_users["owner"].user_id
    )
    await _fork(
        db_pool, visit["id"], PROPERTY_CHECK, parent, '"ok"', seeded_users["member"].user_id
    )
    await _fork(db_pool, visit["id"], PROPERTY_CHECK, parent, '"ok"', seeded_users["owner"].user_id)

    rows = await _open_forks(db_pool, visit["id"])
    # Four rows claim that parent; the reader is asked to choose between the two
    # answers, not between a value and itself.
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_choosing_a_branch_closes_the_fork_and_discards_nothing(
    collab_hunt, as_member: AsyncClient, db_pool, seeded_users
) -> None:
    visit = await _visit(as_member, collab_hunt)
    saved = await _save(as_member, visit["id"], [{"item_key": PROPERTY_CHECK, "value": "ok"}])
    parent = saved[0]["id"]

    kept = await _fork(
        db_pool, visit["id"], PROPERTY_CHECK, parent, '"problem"', seeded_users["owner"].user_id
    )
    await _fork(
        db_pool, visit["id"], PROPERTY_CHECK, parent, '"ok"', seeded_users["member"].user_id
    )
    assert len(await _open_forks(db_pool, visit["id"])) == 2

    # Resolution is an ordinary answer descending from the chosen branch.
    await _save(
        as_member,
        visit["id"],
        [{"item_key": PROPERTY_CHECK, "value": "problem", "prev_entry_id": str(kept)}],
    )

    assert await _open_forks(db_pool, visit["id"]) == []
    current = await db_pool.fetchval(
        "select value from current_visit_entries where visit_id = $1 and item_key = $2",
        visit["id"],
        PROPERTY_CHECK,
    )
    assert current == '"problem"'
    # The losing branch is still on the record — the point of append-only.
    kept_rows = await db_pool.fetchval(
        "select count(*) from visit_entries where visit_id = $1 and item_key = $2",
        visit["id"],
        PROPERTY_CHECK,
    )
    assert kept_rows == 4


@pytest.mark.asyncio
async def test_answering_again_afterwards_also_settles_it(
    collab_hunt, as_member: AsyncClient, db_pool, seeded_users
) -> None:
    """Somebody who overwrites the current value has moved the identity on.

    Nagging about a fork the newest author already replaced would be noise, and
    the losing branch stays readable either way.
    """
    visit = await _visit(as_member, collab_hunt)
    saved = await _save(as_member, visit["id"], [{"item_key": PROPERTY_CHECK, "value": "ok"}])
    parent = saved[0]["id"]

    await _fork(
        db_pool, visit["id"], PROPERTY_CHECK, parent, '"problem"', seeded_users["owner"].user_id
    )
    newest = await _fork(
        db_pool, visit["id"], PROPERTY_CHECK, parent, '"ok"', seeded_users["member"].user_id
    )
    assert len(await _open_forks(db_pool, visit["id"])) == 2

    await _save(
        as_member,
        visit["id"],
        [{"item_key": PROPERTY_CHECK, "value": None, "prev_entry_id": str(newest)}],
    )
    assert await _open_forks(db_pool, visit["id"]) == []


@pytest.mark.asyncio
async def test_a_first_answer_can_never_be_a_conflict(
    collab_hunt, as_member: AsyncClient, db_pool, seeded_users
) -> None:
    """No parent, no fork — two people answering a fresh item just append."""
    visit = await _visit(as_member, collab_hunt)
    await _save(as_member, visit["id"], [{"item_key": PROPERTY_CHECK, "value": "ok"}])
    await db_pool.execute(
        "insert into visit_entries (visit_id, item_key, is_custom, author_user_id, value) "
        "values ($1, $2, false, $3, '\"problem\"'::jsonb)",
        visit["id"],
        PROPERTY_CHECK,
        seeded_users["member"].user_id,
    )
    assert await _open_forks(db_pool, visit["id"]) == []


@pytest.mark.asyncio
async def test_forks_on_different_answers_stay_separate(
    collab_hunt, as_member: AsyncClient, db_pool, seeded_users
) -> None:
    visit = await _visit(as_member, collab_hunt)
    unit = visit["units"][0]["id"]
    saved = await _save(
        as_member,
        visit["id"],
        [
            {"item_key": PROPERTY_CHECK, "value": "ok"},
            {"item_key": UNIT_FACT, "visit_unit_id": unit, "value": "gas"},
        ],
    )
    by_key = {row["item_key"]: row["id"] for row in saved}

    await _fork(
        db_pool,
        visit["id"],
        PROPERTY_CHECK,
        by_key[PROPERTY_CHECK],
        '"problem"',
        seeded_users["owner"].user_id,
    )
    await _fork(
        db_pool,
        visit["id"],
        PROPERTY_CHECK,
        by_key[PROPERTY_CHECK],
        '"ok"',
        seeded_users["member"].user_id,
    )
    await db_pool.execute(
        "insert into visit_entries "
        "(visit_id, item_key, is_custom, visit_unit_id, author_user_id, value, prev_entry_id) "
        "values ($1, $2, false, $3, $4, '\"electric\"'::jsonb, $5), "
        "       ($1, $2, false, $3, $6, '\"induction\"'::jsonb, $5)",
        visit["id"],
        UNIT_FACT,
        unit,
        seeded_users["owner"].user_id,
        by_key[UNIT_FACT],
        seeded_users["member"].user_id,
    )

    rows = await db_pool.fetch(
        "select distinct fork_parent_id from visit_entry_conflicts where visit_id = $1",
        visit["id"],
    )
    assert len(rows) == 2
