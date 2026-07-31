"""Fee Proposals — a tour offers a figure, it never writes one (VC-7, DESIGN §9.7).

The contract these pin down: any member may *offer*; deciding reuses the
Override permission; accepting performs the **ordinary** human write so the
resulting row is indistinguishable from one typed into the drawer; and
rejecting records the decision while leaving the Visit's own figure alone.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


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


async def _propose(client: AsyncClient, visit_id: str, **body) -> object:  # type: ignore[no-untyped-def]
    payload = {"target": "fee_slot", "target_key": "parking", "amount": 75.0, **body}
    return await client.post(f"/v1/visits/{visit_id}/fee-proposals", json=payload)


async def _decide(client: AsyncClient, visit_id: str, proposal_id: str, action: str):  # type: ignore[no-untyped-def]
    return await client.post(
        f"/v1/visits/{visit_id}/fee-proposals/{proposal_id}/decision",
        json={"action": action},
    )


@pytest.mark.asyncio
async def test_a_proposal_changes_nothing_on_the_listing_until_it_is_accepted(
    collab_hunt, as_owner: AsyncClient, db_pool
) -> None:
    visit = await _visit(as_owner, collab_hunt)
    created = await _propose(as_owner, visit["id"], hunt_listing_id=collab_hunt["owner_listing_id"])
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "pending"

    fee = await db_pool.fetchval(
        "select count(*) from fee_checklist where hunt_listing_id = $1 and fee_slot = 'parking'",
        collab_hunt["owner_listing_id"],
    )
    assert fee == 0


@pytest.mark.asyncio
async def test_accepting_a_fee_slot_writes_the_ordinary_checklist_row(
    collab_hunt, as_owner: AsyncClient, db_pool
) -> None:
    visit = await _visit(as_owner, collab_hunt)
    proposal = (
        await _propose(as_owner, visit["id"], hunt_listing_id=collab_hunt["owner_listing_id"])
    ).json()

    decided = await _decide(as_owner, visit["id"], proposal["id"], "accept")
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "accepted"
    assert decided.json()["decided_by"] is not None

    row = await db_pool.fetchrow(
        "select amount, value_state, entered_by from fee_checklist "
        "where hunt_listing_id = $1 and fee_slot = 'parking'",
        collab_hunt["owner_listing_id"],
    )
    assert float(row["amount"]) == 75.0
    # `manual`, and carrying a human's id: indistinguishable from a figure typed
    # into the drawer, which is what makes every downstream provenance marker
    # keep working and is the point of routing through the ordinary writer.
    assert row["value_state"] == "manual"
    assert row["entered_by"] is not None


@pytest.mark.asyncio
async def test_accepting_an_override_target_appends_an_override(
    collab_hunt, as_owner: AsyncClient, db_pool
) -> None:
    visit = await _visit(as_owner, collab_hunt)
    proposal = (
        await _propose(
            as_owner,
            visit["id"],
            hunt_listing_id=collab_hunt["owner_listing_id"],
            target="override",
            target_key="base_rent",
            amount=2150.0,
        )
    ).json()
    accepted = await _decide(as_owner, visit["id"], proposal["id"], "accept")
    assert accepted.status_code == 200, accepted.text

    row = await db_pool.fetchrow(
        "select value, user_id from overrides "
        "where hunt_listing_id = $1 and criterion_key = 'base_rent' "
        "order by created_at desc limit 1",
        collab_hunt["owner_listing_id"],
    )
    assert row is not None
    assert row["user_id"] is not None


@pytest.mark.asyncio
async def test_rejecting_records_the_decision_and_writes_nothing_else(
    collab_hunt, as_owner: AsyncClient, db_pool
) -> None:
    """R7: what the agent said is still what the agent said."""
    visit = await _visit(as_owner, collab_hunt)
    proposal = (
        await _propose(as_owner, visit["id"], hunt_listing_id=collab_hunt["owner_listing_id"])
    ).json()

    rejected = await _decide(as_owner, visit["id"], proposal["id"], "reject")
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"
    # The Visit's own record of the figure survives untouched.
    assert float(rejected.json()["amount"]) == 75.0

    fee = await db_pool.fetchval(
        "select count(*) from fee_checklist where hunt_listing_id = $1 and fee_slot = 'parking'",
        collab_hunt["owner_listing_id"],
    )
    assert fee == 0


@pytest.mark.asyncio
async def test_a_decided_proposal_cannot_be_decided_again(
    collab_hunt, as_owner: AsyncClient
) -> None:
    """Two people tapping accept must not write the cost twice."""
    visit = await _visit(as_owner, collab_hunt)
    proposal = (
        await _propose(as_owner, visit["id"], hunt_listing_id=collab_hunt["owner_listing_id"])
    ).json()
    assert (await _decide(as_owner, visit["id"], proposal["id"], "accept")).status_code == 200

    again = await _decide(as_owner, visit["id"], proposal["id"], "reject")
    assert again.status_code == 409
    assert again.json()["code"] == "fee_proposal_already_decided"


@pytest.mark.asyncio
async def test_reconfirming_updates_the_standing_offer_rather_than_stacking(
    collab_hunt, as_owner: AsyncClient, db_pool
) -> None:
    visit = await _visit(as_owner, collab_hunt)
    first = (
        await _propose(as_owner, visit["id"], hunt_listing_id=collab_hunt["owner_listing_id"])
    ).json()
    second = (
        await _propose(
            as_owner, visit["id"], hunt_listing_id=collab_hunt["owner_listing_id"], amount=95.0
        )
    ).json()

    assert second["id"] == first["id"]
    assert float(second["amount"]) == 95.0
    live = await db_pool.fetchval(
        "select count(*) from visit_fee_proposals where visit_id = $1 and status = 'pending'",
        visit["id"],
    )
    assert live == 1


@pytest.mark.asyncio
async def test_a_visit_cannot_propose_to_another_propertys_listing(
    collab_hunt, as_owner: AsyncClient
) -> None:
    """The loud failure: offering one building's confirmed rent to another."""
    visit = await _visit(as_owner, collab_hunt)
    response = await _propose(
        as_owner, visit["id"], hunt_listing_id=collab_hunt["member_listing_id"]
    )
    assert response.status_code == 422
    assert response.json()["code"] == "listing_not_visited_property"


@pytest.mark.asyncio
async def test_an_unknown_target_is_refused_rather_than_stored(
    collab_hunt, as_owner: AsyncClient
) -> None:
    """A typo would otherwise create a fee line no surface renders."""
    response = await _propose(
        as_owner,
        (await _visit(as_owner, collab_hunt))["id"],
        hunt_listing_id=collab_hunt["owner_listing_id"],
        target_key="valet_parking_deluxe",
    )
    assert response.status_code == 422

    override_typo = await _propose(
        as_owner,
        (await _visit(as_owner, collab_hunt))["id"],
        hunt_listing_id=collab_hunt["owner_listing_id"],
        target="override",
        target_key="parking",
    )
    assert override_typo.status_code == 422


@pytest.mark.asyncio
async def test_a_member_may_offer_a_figure_on_a_listing_they_did_not_add(
    collab_hunt, as_member: AsyncClient
) -> None:
    """Offering is not a cost write — whoever walked the unit heard the number."""
    visit = await _visit(as_member, collab_hunt)
    response = await _propose(
        as_member, visit["id"], hunt_listing_id=collab_hunt["owner_listing_id"]
    )
    assert response.status_code == 201, response.text


@pytest.mark.asyncio
async def test_a_member_cannot_accept_onto_a_listing_they_did_not_add(
    collab_hunt, as_member: AsyncClient, as_owner: AsyncClient, db_pool
) -> None:
    """Deciding *is* the cost write, so it reuses the Override permission."""
    visit = await _visit(as_member, collab_hunt)
    proposal = (
        await _propose(as_member, visit["id"], hunt_listing_id=collab_hunt["owner_listing_id"])
    ).json()

    denied = await _decide(as_member, visit["id"], proposal["id"], "accept")
    assert denied.status_code == 403

    still_pending = await db_pool.fetchval(
        "select status from visit_fee_proposals where id = $1", proposal["id"]
    )
    assert still_pending == "pending"
    wrote = await db_pool.fetchval(
        "select count(*) from fee_checklist where hunt_listing_id = $1 and fee_slot = 'parking'",
        collab_hunt["owner_listing_id"],
    )
    assert wrote == 0


@pytest.mark.asyncio
async def test_a_curator_may_accept_on_any_listing(
    collab_hunt, as_curator: AsyncClient, db_pool
) -> None:
    visit = await _visit(as_curator, collab_hunt)
    proposal = (
        await _propose(as_curator, visit["id"], hunt_listing_id=collab_hunt["owner_listing_id"])
    ).json()
    accepted = await _decide(as_curator, visit["id"], proposal["id"], "accept")
    assert accepted.status_code == 200, accepted.text


@pytest.mark.asyncio
async def test_an_offer_can_be_withdrawn_before_anyone_decides(
    collab_hunt, as_owner: AsyncClient, db_pool
) -> None:
    visit = await _visit(as_owner, collab_hunt)
    proposal = (
        await _propose(as_owner, visit["id"], hunt_listing_id=collab_hunt["owner_listing_id"])
    ).json()

    removed = await as_owner.delete(f"/v1/visits/{visit['id']}/fee-proposals/{proposal['id']}")
    assert removed.status_code == 204
    assert (
        await db_pool.fetchval(
            "select count(*) from visit_fee_proposals where id = $1", proposal["id"]
        )
        == 0
    )


@pytest.mark.asyncio
async def test_accepted_base_rent_corrects_the_plan_that_was_walked(
    collab_hunt, as_owner: AsyncClient, db_pool
) -> None:
    """§9.6: a quoted rent corrects the plan you stood in, not every layout.

    Accepting must write the same *scope* the drawer would for the same edit, or
    the proposal path quietly has a broader effect than typing it by hand.
    """
    created = await as_owner.post(
        f"/v1/hunts/{collab_hunt['hunt_id']}/visits",
        json={
            "property_id": collab_hunt["owner_property_id"],
            "units": [{"label": "4B", "floor_plan_id": collab_hunt["owner_plan_id"]}],
        },
    )
    assert created.status_code == 201, created.text
    visit = created.json()

    proposal = (
        await _propose(
            as_owner,
            visit["id"],
            hunt_listing_id=collab_hunt["owner_listing_id"],
            visit_unit_id=visit["units"][0]["id"],
            target="override",
            target_key="base_rent",
            amount=2150.0,
        )
    ).json()
    assert (await _decide(as_owner, visit["id"], proposal["id"], "accept")).status_code == 200

    row = await db_pool.fetchrow(
        "select target_scope, floor_plan_id, applicability from overrides "
        "where hunt_listing_id = $1 and criterion_key = 'base_rent' "
        "order by created_at desc limit 1",
        collab_hunt["owner_listing_id"],
    )
    assert row["target_scope"] == "floor_plan"
    assert str(row["floor_plan_id"]) == collab_hunt["owner_plan_id"]
    assert row["applicability"] == "specific_floor_plans"


@pytest.mark.asyncio
async def test_base_rent_from_a_described_unit_falls_back_to_the_property(
    collab_hunt, as_owner: AsyncClient, db_pool
) -> None:
    """A unit that matched no advertised plan has none to correct."""
    visit = await _visit(as_owner, collab_hunt)  # a described "4B", no floor plan
    proposal = (
        await _propose(
            as_owner,
            visit["id"],
            hunt_listing_id=collab_hunt["owner_listing_id"],
            visit_unit_id=visit["units"][0]["id"],
            target="override",
            target_key="base_rent",
            amount=2150.0,
        )
    ).json()
    assert (await _decide(as_owner, visit["id"], proposal["id"], "accept")).status_code == 200

    row = await db_pool.fetchrow(
        "select target_scope, floor_plan_id from overrides "
        "where hunt_listing_id = $1 and criterion_key = 'base_rent' "
        "order by created_at desc limit 1",
        collab_hunt["owner_listing_id"],
    )
    assert row["target_scope"] == "property"
    assert row["floor_plan_id"] is None
