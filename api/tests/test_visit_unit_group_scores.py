"""The Unit Group roll-up (VC-8, DESIGN §9.7, plan §6).

Four rules, each of which changes the number a reader sees:

1. a door's score is the mean **across members** of each member's own
   unit-scope Impression ratings — per member first, so a prolific rater does
   not outvote a terse one, and building-scope Impressions never count;
2. the **latest** tour of a door wins, because a second showing is a correction;
3. the **best** door represents its Unit Group, matching the Display Floor Plan
   rule; and
4. a described unit matching no advertised Unit Group produces **no row** —
   minting a group would contradict §3.

These live in the `visit_unit_group_scores` view, so the tests read it directly.
"""

from __future__ import annotations

import json

import pytest
from httpx import AsyncClient

# Unit-scope Impressions in the seeded template, and one property-scoped one.
UNIT_IMPRESSIONS = ("verdict_noise", "verdict_light")
PROPERTY_IMPRESSION = "verdict_safety"


async def _visit(client: AsyncClient, collab_hunt, units: list[dict]) -> dict:  # type: ignore[no-untyped-def]
    created = await client.post(
        f"/v1/hunts/{collab_hunt['hunt_id']}/visits",
        json={"property_id": collab_hunt["owner_property_id"], "units": units},
    )
    assert created.status_code == 201, created.text
    started = await client.patch(f"/v1/visits/{created.json()['id']}", json={"action": "start"})
    assert started.status_code == 200, started.text
    return created.json()


async def _rate(db_pool, visit_id: str, unit_id: str | None, member: str, item: str, value: int):
    """Write a rating directly: these tests are about the view, not the route."""
    await db_pool.execute(
        "insert into visit_entries "
        "(visit_id, item_key, is_custom, visit_unit_id, owner_user_id, author_user_id, value) "
        "values ($1, $2, false, $3, $4, $4, to_jsonb($5::numeric))",
        visit_id,
        item,
        unit_id,
        member,
        value,
    )


async def _rollup(db_pool, listing_id: str) -> list:
    return await db_pool.fetch(
        "select unit_group_key, score, unit_count, rater_count, best_visit_unit_id "
        "from visit_unit_group_scores where hunt_listing_id = $1 order by unit_group_key",
        listing_id,
    )


@pytest.mark.asyncio
async def test_a_doors_score_averages_members_not_ratings(
    collab_hunt, as_owner: AsyncClient, db_pool, seeded_users
) -> None:
    """Per member first, then across members.

    The owner rates two items (2 and 4 → 3); the member rates one (5). The
    answer is 4.0, not the flat mean of 3.67 — otherwise whoever fills in the
    most fields quietly gets the loudest vote.
    """
    visit = await _visit(as_owner, collab_hunt, [{"label": "4B", "beds": 2, "baths": 1}])
    unit = visit["units"][0]["id"]
    owner, member = seeded_users["owner"].user_id, seeded_users["member"].user_id

    await _rate(db_pool, visit["id"], unit, owner, UNIT_IMPRESSIONS[0], 2)
    await _rate(db_pool, visit["id"], unit, owner, UNIT_IMPRESSIONS[1], 4)
    await _rate(db_pool, visit["id"], unit, member, UNIT_IMPRESSIONS[0], 5)

    rows = await _rollup(db_pool, collab_hunt["owner_listing_id"])
    assert len(rows) == 1
    assert float(rows[0]["score"]) == 4.0
    assert rows[0]["rater_count"] == 2


@pytest.mark.asyncio
async def test_building_impressions_never_reach_the_roll_up(
    collab_hunt, as_owner: AsyncClient, db_pool, seeded_users
) -> None:
    """Plan Q4: they are identical on every row of the Property.

    Including them would compress the differences between rows without adding
    information — the opposite of what a comparison column is for.
    """
    visit = await _visit(as_owner, collab_hunt, [{"label": "4B", "beds": 2, "baths": 1}])
    unit = visit["units"][0]["id"]
    owner = seeded_users["owner"].user_id

    await _rate(db_pool, visit["id"], unit, owner, UNIT_IMPRESSIONS[0], 2)
    await _rate(db_pool, visit["id"], None, owner, PROPERTY_IMPRESSION, 5)

    rows = await _rollup(db_pool, collab_hunt["owner_listing_id"])
    assert float(rows[0]["score"]) == 2.0


@pytest.mark.asyncio
async def test_the_latest_tour_of_a_door_replaces_the_earlier_one(
    collab_hunt, as_owner: AsyncClient, db_pool, seeded_users
) -> None:
    """A second showing is a correction, not a competitor.

    Best-of across time would let a rosy first impression outrank the careful
    second look — which is exactly backwards.
    """
    owner = seeded_users["owner"].user_id
    first = await _visit(as_owner, collab_hunt, [{"label": "4B", "beds": 2, "baths": 1}])
    await _rate(db_pool, first["id"], first["units"][0]["id"], owner, UNIT_IMPRESSIONS[0], 5)
    assert float((await _rollup(db_pool, collab_hunt["owner_listing_id"]))[0]["score"]) == 5.0

    second = await _visit(as_owner, collab_hunt, [{"label": "4B", "beds": 2, "baths": 1}])
    await _rate(db_pool, second["id"], second["units"][0]["id"], owner, UNIT_IMPRESSIONS[0], 2)
    # Same label, later tour: the group follows the correction.
    await db_pool.execute(
        "update visits set started_at = now() + interval '1 day' where id = $1", second["id"]
    )

    rows = await _rollup(db_pool, collab_hunt["owner_listing_id"])
    assert float(rows[0]["score"]) == 2.0
    assert rows[0]["unit_count"] == 1


@pytest.mark.asyncio
async def test_the_best_door_represents_its_unit_group(
    collab_hunt, as_owner: AsyncClient, db_pool, seeded_users
) -> None:
    visit = await _visit(
        as_owner,
        collab_hunt,
        [{"label": "4B", "beds": 2, "baths": 1}, {"label": "7C", "beds": 2, "baths": 1}],
    )
    owner = seeded_users["owner"].user_id
    good, bad = visit["units"][0]["id"], visit["units"][1]["id"]
    await _rate(db_pool, visit["id"], good, owner, UNIT_IMPRESSIONS[0], 4)
    await _rate(db_pool, visit["id"], bad, owner, UNIT_IMPRESSIONS[0], 1)

    rows = await _rollup(db_pool, collab_hunt["owner_listing_id"])
    assert len(rows) == 1
    assert float(rows[0]["score"]) == 4.0
    assert rows[0]["unit_count"] == 2
    assert str(rows[0]["best_visit_unit_id"]) == good


@pytest.mark.asyncio
async def test_a_unit_matching_no_advertised_group_produces_no_row(
    collab_hunt, as_owner: AsyncClient, db_pool, seeded_users
) -> None:
    """Rule 4. Minting a Unit Group would contradict §3.

    Groups derive from a Property's Floor Plans; the app never invents one. The
    tour is still visible on the Visit and in the drawer — showing nothing on
    the Overview beats showing a row that does not exist.
    """
    visit = await _visit(as_owner, collab_hunt, [{"label": "PH", "beds": 9, "baths": 9}])
    await _rate(
        db_pool,
        visit["id"],
        visit["units"][0]["id"],
        seeded_users["owner"].user_id,
        UNIT_IMPRESSIONS[0],
        5,
    )
    assert await _rollup(db_pool, collab_hunt["owner_listing_id"]) == []


@pytest.mark.asyncio
async def test_a_cancelled_tour_is_not_evidence(
    collab_hunt, as_owner: AsyncClient, db_pool, seeded_users
) -> None:
    visit = await _visit(as_owner, collab_hunt, [{"label": "4B", "beds": 2, "baths": 1}])
    await _rate(
        db_pool,
        visit["id"],
        visit["units"][0]["id"],
        seeded_users["owner"].user_id,
        UNIT_IMPRESSIONS[0],
        4,
    )
    assert len(await _rollup(db_pool, collab_hunt["owner_listing_id"])) == 1

    await as_owner.patch(f"/v1/visits/{visit['id']}", json={"action": "cancel"})
    assert await _rollup(db_pool, collab_hunt["owner_listing_id"]) == []


@pytest.mark.asyncio
async def test_an_unrated_tour_produces_no_score(
    collab_hunt, as_owner: AsyncClient, db_pool
) -> None:
    """Walking a unit is not a rating. No opinion, no number."""
    await _visit(as_owner, collab_hunt, [{"label": "4B", "beds": 2, "baths": 1}])
    assert await _rollup(db_pool, collab_hunt["owner_listing_id"]) == []


@pytest.mark.asyncio
async def test_a_cleared_rating_stops_counting(
    collab_hunt, as_owner: AsyncClient, db_pool, seeded_users
) -> None:
    """Append-only clearing must not leave a stale number in the roll-up."""
    visit = await _visit(as_owner, collab_hunt, [{"label": "4B", "beds": 2, "baths": 1}])
    unit, owner = visit["units"][0]["id"], seeded_users["owner"].user_id
    await _rate(db_pool, visit["id"], unit, owner, UNIT_IMPRESSIONS[0], 4)

    # The tombstone the UI writes when a rating is cleared.
    await db_pool.execute(
        "insert into visit_entries "
        "(visit_id, item_key, is_custom, visit_unit_id, owner_user_id, author_user_id, value) "
        "values ($1, $2, false, $3, $4, $4, null)",
        visit["id"],
        UNIT_IMPRESSIONS[0],
        unit,
        owner,
    )
    assert await _rollup(db_pool, collab_hunt["owner_listing_id"]) == []


@pytest.mark.asyncio
async def test_the_roll_up_is_scoped_to_hunt_members(
    collab_hunt, as_owner: AsyncClient, db_pool, seeded_users
) -> None:
    """`security_invoker`: the view inherits the base tables' RLS.

    Exercised as PostgREST reaches it — a plain `authenticated` role carrying a
    user's claims — rather than through a route, because Visit reads are
    direct-Supabase and there is no GET endpoint to go through.
    """
    visit = await _visit(as_owner, collab_hunt, [{"label": "4B", "beds": 2, "baths": 1}])
    await _rate(
        db_pool,
        visit["id"],
        visit["units"][0]["id"],
        seeded_users["owner"].user_id,
        UNIT_IMPRESSIONS[0],
        4,
    )

    async def visible_to(user_id: str) -> int:
        async with db_pool.acquire() as connection, connection.transaction():
            await connection.execute("set local role authenticated")
            await connection.execute(
                "select set_config('request.jwt.claims', $1, true)",
                json.dumps({"sub": user_id, "role": "authenticated"}),
            )
            return await connection.fetchval("select count(*) from visit_unit_group_scores")

    assert await visible_to(seeded_users["owner"].user_id) == 1
    assert await visible_to("33333333-3333-3333-3333-333333333333") == 0
