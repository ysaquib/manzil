"""The Visit Checklist answer store (VC-3, DESIGN §9.7).

Scope is the *item's*, not the caller's; entries are append-only; and a
Question's typed answer is the only thing that marks it asked.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

# Real keys from the seeded template (version 1).
PROPERTY_CHECK = "prep_reviews"  # property-scoped check
UNIT_FACT = "kitchen_stove_type"  # unit-scoped fact
UNIT_IMPRESSION = "verdict_noise"  # unit-scoped impression, keyed per member
PROPERTY_QUESTION = "hist_bed_bugs"  # property-scoped critical question
PROPERTY_IMPRESSION = "verdict_safety"  # property-scoped impression


async def _visit_with_units(client: AsyncClient, collab_hunt) -> dict:  # type: ignore[no-untyped-def]
    created = await client.post(
        f"/v1/hunts/{collab_hunt['hunt_id']}/visits",
        json={
            "property_id": collab_hunt["owner_property_id"],
            "units": [
                {"label": "4B", "beds": 2, "baths": 2},
                {"label": "2A", "beds": 1, "baths": 1},
            ],
        },
    )
    assert created.status_code == 201, created.text
    return created.json()


async def _save(client: AsyncClient, visit_id: str, entries: list[dict]):  # type: ignore[no-untyped-def]
    return await client.put(f"/v1/visits/{visit_id}/entries", json={"entries": entries})


@pytest.mark.asyncio
async def test_property_item_records_once_while_a_unit_item_records_per_unit(
    collab_hunt, as_member: AsyncClient
) -> None:
    visit = await _visit_with_units(as_member, collab_hunt)
    unit_a, unit_b = visit["units"][0]["id"], visit["units"][1]["id"]

    saved = await _save(
        as_member,
        visit["id"],
        [
            {"item_key": PROPERTY_CHECK, "value": "ok"},
            {"item_key": UNIT_FACT, "visit_unit_id": unit_a, "value": "gas"},
            {"item_key": UNIT_FACT, "visit_unit_id": unit_b, "value": "electric"},
        ],
    )
    assert saved.status_code == 200, saved.text
    rows = saved.json()

    # One property answer, no unit attached.
    prop = [r for r in rows if r["item_key"] == PROPERTY_CHECK]
    assert len(prop) == 1
    assert prop[0]["visit_unit_id"] is None

    # The unit-scoped fact is genuinely two separate answers, not one overwritten.
    facts = {r["visit_unit_id"]: r["value"] for r in rows if r["item_key"] == UNIT_FACT}
    assert facts == {unit_a: "gas", unit_b: "electric"}


@pytest.mark.asyncio
async def test_property_item_written_against_a_unit_is_rejected_not_coerced(
    collab_hunt, as_member: AsyncClient
) -> None:
    """The headline rule: a mis-filed answer fails loudly rather than being
    silently re-filed, because silently re-filing is the failure mode the whole
    scope design exists to prevent."""
    visit = await _visit_with_units(as_member, collab_hunt)
    response = await _save(
        as_member,
        visit["id"],
        [{"item_key": PROPERTY_CHECK, "visit_unit_id": visit["units"][0]["id"], "value": "ok"}],
    )
    assert response.status_code == 422
    assert response.json()["code"] == "checklist_scope_mismatch"

    # Nothing landed — a rejected batch is not partially applied.
    read = await _save(as_member, visit["id"], [{"item_key": PROPERTY_CHECK, "value": "ok"}])
    assert read.status_code == 200


@pytest.mark.asyncio
async def test_unit_item_without_a_unit_is_rejected(collab_hunt, as_member: AsyncClient) -> None:
    visit = await _visit_with_units(as_member, collab_hunt)
    response = await _save(as_member, visit["id"], [{"item_key": UNIT_FACT, "value": "gas"}])
    assert response.status_code == 422
    assert response.json()["code"] == "checklist_scope_mismatch"


@pytest.mark.asyncio
async def test_a_unit_from_another_visit_is_refused(collab_hunt, as_member: AsyncClient) -> None:
    first = await _visit_with_units(as_member, collab_hunt)
    second = await _visit_with_units(as_member, collab_hunt)
    response = await _save(
        as_member,
        first["id"],
        [{"item_key": UNIT_FACT, "visit_unit_id": second["units"][0]["id"], "value": "gas"}],
    )
    assert response.status_code == 422
    assert response.json()["code"] == "visit_unit_not_on_visit"


@pytest.mark.asyncio
async def test_unknown_item_is_refused(collab_hunt, as_member: AsyncClient) -> None:
    visit = await _visit_with_units(as_member, collab_hunt)
    response = await _save(as_member, visit["id"], [{"item_key": "not_an_item", "value": 1}])
    assert response.status_code == 422
    assert response.json()["code"] == "unknown_checklist_item"


@pytest.mark.asyncio
async def test_answers_persist_and_reload(collab_hunt, as_member: AsyncClient, db_pool) -> None:
    visit = await _visit_with_units(as_member, collab_hunt)
    unit = visit["units"][0]["id"]
    await _save(
        as_member,
        visit["id"],
        [
            {"item_key": PROPERTY_CHECK, "value": "ok", "note": "three years of complaints"},
            {"item_key": UNIT_FACT, "visit_unit_id": unit, "value": "gas"},
        ],
    )
    rows = await db_pool.fetch(
        "select item_key, value, note from current_visit_entries "
        "where visit_id = $1 order by item_key",
        visit["id"],
    )
    stored = {row["item_key"]: (row["value"], row["note"]) for row in rows}
    assert stored[PROPERTY_CHECK] == ('"ok"', "three years of complaints")
    assert stored[UNIT_FACT] == ('"gas"', None)


@pytest.mark.asyncio
async def test_writing_again_appends_and_the_newest_wins(
    collab_hunt, as_member: AsyncClient, db_pool
) -> None:
    visit = await _visit_with_units(as_member, collab_hunt)
    unit = visit["units"][0]["id"]
    await _save(
        as_member, visit["id"], [{"item_key": UNIT_FACT, "visit_unit_id": unit, "value": "gas"}]
    )
    second = await _save(
        as_member,
        visit["id"],
        [{"item_key": UNIT_FACT, "visit_unit_id": unit, "value": "induction"}],
    )
    assert second.json()[0]["value"] == "induction"

    history = await db_pool.fetchval(
        "select count(*) from visit_entries where visit_id = $1 and item_key = $2",
        visit["id"],
        UNIT_FACT,
    )
    # Append-only: the first answer is still there, which is what makes the
    # byline and VC-6's conflict fork possible.
    assert history == 2


@pytest.mark.asyncio
async def test_a_null_value_is_the_tombstone_rather_than_a_delete(
    collab_hunt, as_member: AsyncClient, db_pool
) -> None:
    visit = await _visit_with_units(as_member, collab_hunt)
    unit = visit["units"][0]["id"]
    await _save(
        as_member, visit["id"], [{"item_key": UNIT_FACT, "visit_unit_id": unit, "value": "gas"}]
    )
    cleared = await _save(
        as_member, visit["id"], [{"item_key": UNIT_FACT, "visit_unit_id": unit, "value": None}]
    )
    assert cleared.json()[0]["value"] is None
    assert (
        await db_pool.fetchval(
            "select count(*) from visit_entries where visit_id = $1 and item_key = $2",
            visit["id"],
            UNIT_FACT,
        )
        == 2
    )


@pytest.mark.asyncio
async def test_impressions_are_keyed_per_member_while_facts_are_shared(
    collab_hunt, as_member: AsyncClient, as_curator: AsyncClient, seeded_users, db_pool
) -> None:
    visit = await _visit_with_units(as_member, collab_hunt)
    unit = visit["units"][0]["id"]

    await _save(
        as_member, visit["id"], [{"item_key": UNIT_IMPRESSION, "visit_unit_id": unit, "value": 2}]
    )
    await _save(
        as_curator, visit["id"], [{"item_key": UNIT_IMPRESSION, "visit_unit_id": unit, "value": 4}]
    )

    rows = await db_pool.fetch(
        "select owner_user_id, value from current_visit_entries "
        "where visit_id = $1 and item_key = $2",
        visit["id"],
        UNIT_IMPRESSION,
    )
    # Two current rows: one opinion each, neither overwriting the other.
    assert len(rows) == 2
    by_owner = {str(r["owner_user_id"]): r["value"] for r in rows}
    assert by_owner[seeded_users["member"].user_id] == "2"
    assert by_owner[seeded_users["curator"].user_id] == "4"

    # A shared Fact behaves the opposite way: the second member overwrites.
    await _save(
        as_member, visit["id"], [{"item_key": UNIT_FACT, "visit_unit_id": unit, "value": "gas"}]
    )
    await _save(
        as_curator,
        visit["id"],
        [{"item_key": UNIT_FACT, "visit_unit_id": unit, "value": "electric"}],
    )
    shared = await db_pool.fetch(
        "select owner_user_id, value, author_user_id from current_visit_entries "
        "where visit_id = $1 and item_key = $2",
        visit["id"],
        UNIT_FACT,
    )
    assert len(shared) == 1
    assert shared[0]["owner_user_id"] is None
    assert shared[0]["value"] == '"electric"'
    # …and it still says who wrote it, which is the byline.
    assert str(shared[0]["author_user_id"]) == seeded_users["curator"].user_id


@pytest.mark.asyncio
async def test_a_question_carries_its_answer_as_text_not_a_value(
    collab_hunt, as_member: AsyncClient
) -> None:
    visit = await _visit_with_units(as_member, collab_hunt)

    # The typed answer *is* the checkmark, so a separate value would be a second,
    # contradictory source of "was this asked".
    rejected = await _save(as_member, visit["id"], [{"item_key": PROPERTY_QUESTION, "value": True}])
    assert rejected.status_code == 422
    assert rejected.json()["code"] == "checklist_value_not_allowed"

    answered = await _save(
        as_member,
        visit["id"],
        [{"item_key": PROPERTY_QUESTION, "answer_text": "  No incidents on record  "}],
    )
    assert answered.status_code == 200
    assert answered.json()[0]["answer_text"] == "No incidents on record"

    # A blank answer is no answer — it cannot mark the question asked.
    blank = await _save(
        as_member, visit["id"], [{"item_key": PROPERTY_QUESTION, "answer_text": "   "}]
    )
    assert blank.status_code == 200
    assert blank.json()[0]["answer_text"] is None


@pytest.mark.asyncio
async def test_property_scoped_impression_is_recorded_once_per_member(
    collab_hunt, as_member: AsyncClient, db_pool
) -> None:
    """§21's building half: you would answer these identically for every unit,
    so they are asked once (DESIGN §9.7, R10)."""
    visit = await _visit_with_units(as_member, collab_hunt)
    saved = await _save(as_member, visit["id"], [{"item_key": PROPERTY_IMPRESSION, "value": 4}])
    assert saved.status_code == 200
    assert saved.json()[0]["visit_unit_id"] is None
    assert saved.json()[0]["owner_user_id"] is not None

    with_unit = await _save(
        as_member,
        visit["id"],
        [{"item_key": PROPERTY_IMPRESSION, "visit_unit_id": visit["units"][0]["id"], "value": 4}],
    )
    assert with_unit.status_code == 422


@pytest.mark.asyncio
async def test_custom_items_are_answerable_by_their_id(collab_hunt, as_member: AsyncClient) -> None:
    visit = await _visit_with_units(as_member, collab_hunt)
    item = await as_member.post(
        f"/v1/visits/{visit['id']}/custom-items",
        json={
            "section_key": "kitchen",
            "kind": "check",
            "scope": "unit",
            "label": "Room for the stand mixer",
        },
    )
    assert item.status_code == 201
    saved = await _save(
        as_member,
        visit["id"],
        [
            {
                "item_key": item.json()["id"],
                "is_custom": True,
                "visit_unit_id": visit["units"][0]["id"],
                "value": "ok",
            }
        ],
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()[0]["is_custom"] is True

    # A custom item's scope is enforced exactly like a template item's.
    mismatch = await _save(
        as_member, visit["id"], [{"item_key": item.json()["id"], "is_custom": True, "value": "ok"}]
    )
    assert mismatch.status_code == 422
    assert mismatch.json()["code"] == "checklist_scope_mismatch"


@pytest.mark.asyncio
async def test_prev_entry_id_is_stored_for_the_offline_fork(
    collab_hunt, as_member: AsyncClient
) -> None:
    visit = await _visit_with_units(as_member, collab_hunt)
    unit = visit["units"][0]["id"]
    first = await _save(
        as_member, visit["id"], [{"item_key": UNIT_FACT, "visit_unit_id": unit, "value": "gas"}]
    )
    prev_id = first.json()[0]["id"]
    second = await _save(
        as_member,
        visit["id"],
        [
            {
                "item_key": UNIT_FACT,
                "visit_unit_id": unit,
                "value": "electric",
                "prev_entry_id": prev_id,
            }
        ],
    )
    assert second.json()[0]["prev_entry_id"] == prev_id


@pytest.mark.asyncio
async def test_an_outsider_cannot_write_answers(
    collab_hunt, as_member: AsyncClient, as_outsider: AsyncClient
) -> None:
    visit = await _visit_with_units(as_member, collab_hunt)
    denied = await _save(as_outsider, visit["id"], [{"item_key": PROPERTY_CHECK, "value": "ok"}])
    assert denied.status_code == 404


@pytest.mark.asyncio
async def test_batch_requires_at_least_one_entry(collab_hunt, as_member: AsyncClient) -> None:
    visit = await _visit_with_units(as_member, collab_hunt)
    assert (await _save(as_member, visit["id"], [])).status_code == 422
