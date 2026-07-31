"""The Visit defect log and Check→Defect promotion (VC-4, DESIGN §9.7).

The design claim being tested: the defect log fills itself during the walk, so
nobody has to transcribe into it afterwards — and doing so never costs the
member control over what ends up in it.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

UNIT_CHECK = "kitchen_disposal"  # unit-scoped check
PROPERTY_CHECK = "prep_reviews"  # property-scoped check
UNIT_FACT = "kitchen_stove_type"  # unit-scoped fact — must never promote


async def _visit(client: AsyncClient, collab_hunt) -> dict:  # type: ignore[no-untyped-def]
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


async def _defects(db_pool, visit_id: str, *, include_deleted: bool = False):  # type: ignore[no-untyped-def]
    clause = "" if include_deleted else " and deleted_at is null"
    return await db_pool.fetch(
        f"select * from visit_defects where visit_id = $1{clause} order by created_at",
        visit_id,
    )


@pytest.mark.asyncio
async def test_a_failed_check_promotes_to_one_defect_with_its_unit_and_origin(
    collab_hunt, as_member: AsyncClient, db_pool
) -> None:
    visit = await _visit(as_member, collab_hunt)
    unit = visit["units"][0]["id"]

    saved = await _save(
        as_member,
        visit["id"],
        [
            {
                "item_key": UNIT_CHECK,
                "visit_unit_id": unit,
                "value": "problem",
                "note": "water stain under the sink",
            }
        ],
    )
    assert saved.status_code == 200, saved.text

    rows = await _defects(db_pool, visit["id"])
    assert len(rows) == 1
    defect = rows[0]
    assert defect["from_item_key"] == UNIT_CHECK
    assert str(defect["visit_unit_id"]) == unit
    # The title is the checklist item's own label, so the log reads as prose.
    assert defect["title"] == "Ran the disposal"
    # The note travels with it — that note is usually the description.
    assert defect["note"] == "water stain under the sink"
    # Unrated rather than assigned a number nobody chose.
    assert defect["severity"] is None


@pytest.mark.asyncio
async def test_a_passing_check_and_a_fact_never_promote(
    collab_hunt, as_member: AsyncClient, db_pool
) -> None:
    visit = await _visit(as_member, collab_hunt)
    unit = visit["units"][0]["id"]
    await _save(
        as_member,
        visit["id"],
        [
            {"item_key": UNIT_CHECK, "visit_unit_id": unit, "value": "ok"},
            # A Fact whose value happens to be the string "problem" is still a
            # Fact — promotion keys off the item's kind, not its value.
            {"item_key": UNIT_FACT, "visit_unit_id": unit, "value": "problem"},
        ],
    )
    assert await _defects(db_pool, visit["id"]) == []


@pytest.mark.asyncio
async def test_promotion_is_once_only_however_many_times_it_is_marked(
    collab_hunt, as_member: AsyncClient, db_pool
) -> None:
    visit = await _visit(as_member, collab_hunt)
    unit = visit["units"][0]["id"]
    problem = {"item_key": UNIT_CHECK, "visit_unit_id": unit, "value": "problem"}

    await _save(as_member, visit["id"], [problem])
    await _save(as_member, visit["id"], [problem])
    # Clear it, then mark it again — still one defect.
    await _save(as_member, visit["id"], [{**problem, "value": None}])
    await _save(as_member, visit["id"], [problem])

    assert len(await _defects(db_pool, visit["id"], include_deleted=True)) == 1


@pytest.mark.asyncio
async def test_the_same_check_promotes_separately_for_each_unit(
    collab_hunt, as_member: AsyncClient, db_pool
) -> None:
    """Two units with the same broken thing are two problems, not one."""
    visit = await _visit(as_member, collab_hunt)
    unit_a, unit_b = visit["units"][0]["id"], visit["units"][1]["id"]
    await _save(
        as_member,
        visit["id"],
        [
            {"item_key": UNIT_CHECK, "visit_unit_id": unit_a, "value": "problem"},
            {"item_key": UNIT_CHECK, "visit_unit_id": unit_b, "value": "problem"},
        ],
    )
    rows = await _defects(db_pool, visit["id"])
    assert {str(row["visit_unit_id"]) for row in rows} == {unit_a, unit_b}


@pytest.mark.asyncio
async def test_a_property_check_promotes_against_the_building(
    collab_hunt, as_member: AsyncClient, db_pool
) -> None:
    visit = await _visit(as_member, collab_hunt)
    await _save(as_member, visit["id"], [{"item_key": PROPERTY_CHECK, "value": "problem"}])
    rows = await _defects(db_pool, visit["id"])
    assert len(rows) == 1
    # Null means the building, not an omission.
    assert rows[0]["visit_unit_id"] is None


@pytest.mark.asyncio
async def test_deleting_a_defect_leaves_the_checks_answer_alone(
    collab_hunt, as_member: AsyncClient, db_pool
) -> None:
    """The two are separate records of separate things: that a test failed, and
    what the problem was."""
    visit = await _visit(as_member, collab_hunt)
    unit = visit["units"][0]["id"]
    await _save(
        as_member,
        visit["id"],
        [{"item_key": UNIT_CHECK, "visit_unit_id": unit, "value": "problem"}],
    )
    defect = (await _defects(db_pool, visit["id"]))[0]

    removed = await as_member.delete(f"/v1/visits/{visit['id']}/defects/{defect['id']}")
    assert removed.status_code == 204

    assert await _defects(db_pool, visit["id"]) == []
    answer = await db_pool.fetchval(
        "select value from current_visit_entries where visit_id = $1 and item_key = $2",
        visit["id"],
        UNIT_CHECK,
    )
    assert answer == '"problem"'


@pytest.mark.asyncio
async def test_a_deleted_defect_is_not_resurrected_by_marking_again(
    collab_hunt, as_member: AsyncClient, db_pool
) -> None:
    """Removing a defect is deliberate; toggling the check must not undo it."""
    visit = await _visit(as_member, collab_hunt)
    unit = visit["units"][0]["id"]
    problem = {"item_key": UNIT_CHECK, "visit_unit_id": unit, "value": "problem"}
    await _save(as_member, visit["id"], [problem])
    defect = (await _defects(db_pool, visit["id"]))[0]
    await as_member.delete(f"/v1/visits/{visit['id']}/defects/{defect['id']}")

    await _save(as_member, visit["id"], [{**problem, "value": None}])
    await _save(as_member, visit["id"], [problem])

    assert await _defects(db_pool, visit["id"]) == []
    assert len(await _defects(db_pool, visit["id"], include_deleted=True)) == 1


@pytest.mark.asyncio
async def test_a_defect_can_be_logged_by_hand_and_edited(
    collab_hunt, as_member: AsyncClient
) -> None:
    visit = await _visit(as_member, collab_hunt)
    created = await as_member.post(
        f"/v1/visits/{visit['id']}/defects",
        json={
            "title": "  Fresh caulk in one isolated spot  ",
            "visit_unit_id": visit["units"][0]["id"],
            "severity": 2,
        },
    )
    assert created.status_code == 201
    assert created.json()["title"] == "Fresh caulk in one isolated spot"
    assert created.json()["from_item_key"] is None

    patched = await as_member.patch(
        f"/v1/visits/{visit['id']}/defects/{created.json()['id']}",
        json={"severity": 4, "promised_in_writing": True, "note": "photographed"},
    )
    assert patched.status_code == 200
    assert patched.json()["severity"] == 4
    assert patched.json()["promised_in_writing"] is True
    assert patched.json()["note"] == "photographed"


@pytest.mark.asyncio
async def test_a_hand_logged_defect_defaults_to_the_building(
    collab_hunt, as_member: AsyncClient
) -> None:
    visit = await _visit(as_member, collab_hunt)
    created = await as_member.post(
        f"/v1/visits/{visit['id']}/defects", json={"title": "Trash area overflowing"}
    )
    assert created.status_code == 201
    assert created.json()["visit_unit_id"] is None
    assert created.json()["severity"] is None


@pytest.mark.asyncio
async def test_a_unit_from_another_visit_is_refused(collab_hunt, as_member: AsyncClient) -> None:
    first = await _visit(as_member, collab_hunt)
    second = await _visit(as_member, collab_hunt)
    response = await as_member.post(
        f"/v1/visits/{first['id']}/defects",
        json={"title": "Impossible", "visit_unit_id": second["units"][0]["id"]},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "visit_unit_not_on_visit"


@pytest.mark.asyncio
async def test_editing_a_deleted_defect_is_a_404(collab_hunt, as_member: AsyncClient) -> None:
    visit = await _visit(as_member, collab_hunt)
    created = await as_member.post(f"/v1/visits/{visit['id']}/defects", json={"title": "Gone"})
    defect_id = created.json()["id"]
    await as_member.delete(f"/v1/visits/{visit['id']}/defects/{defect_id}")

    assert (
        await as_member.patch(f"/v1/visits/{visit['id']}/defects/{defect_id}", json={"severity": 3})
    ).status_code == 404
    assert (
        await as_member.delete(f"/v1/visits/{visit['id']}/defects/{defect_id}")
    ).status_code == 404


@pytest.mark.asyncio
async def test_another_member_can_edit_a_defect_they_did_not_log(
    collab_hunt, as_member: AsyncClient, as_curator: AsyncClient
) -> None:
    """On a tour the person holding the phone is often not the person who spotted
    the problem, so a defect is shared knowledge rather than one member's."""
    visit = await _visit(as_member, collab_hunt)
    created = await as_member.post(
        f"/v1/visits/{visit['id']}/defects", json={"title": "Window won't latch"}
    )
    patched = await as_curator.patch(
        f"/v1/visits/{visit['id']}/defects/{created.json()['id']}", json={"severity": 3}
    )
    assert patched.status_code == 200


@pytest.mark.asyncio
async def test_an_outsider_cannot_see_or_log_defects(
    collab_hunt, as_member: AsyncClient, as_outsider: AsyncClient, seeded_users
) -> None:
    visit = await _visit(as_member, collab_hunt)
    await as_member.post(f"/v1/visits/{visit['id']}/defects", json={"title": "Private"})

    denied = await as_outsider.post(f"/v1/visits/{visit['id']}/defects", json={"title": "Intruder"})
    assert denied.status_code == 404

    rows = (
        seeded_users["outsider"]
        .supabase.table("visit_defects")
        .select("id")
        .eq("visit_id", visit["id"])
        .execute()
        .data
        or []
    )
    assert rows == []


@pytest.mark.asyncio
async def test_a_custom_check_promotes_under_its_own_label(
    collab_hunt, as_member: AsyncClient, db_pool
) -> None:
    visit = await _visit(as_member, collab_hunt)
    item = await as_member.post(
        f"/v1/visits/{visit['id']}/custom-items",
        json={
            "section_key": "kitchen",
            "kind": "check",
            "scope": "unit",
            "label": "Room for the stand mixer",
        },
    )
    await _save(
        as_member,
        visit["id"],
        [
            {
                "item_key": item.json()["id"],
                "is_custom": True,
                "visit_unit_id": visit["units"][0]["id"],
                "value": "problem",
            }
        ],
    )
    rows = await _defects(db_pool, visit["id"])
    assert len(rows) == 1
    assert rows[0]["title"] == "Room for the stand mixer"
