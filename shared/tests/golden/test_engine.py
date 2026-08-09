"""Golden tests for the scoring engine (P0-3, DESIGN §9.3, §9.4).

Each golden asserts the EXACT breakdown via the pinned §9.3 contract shape
(`ScoreBreakdown.to_contract()`). A change to the engine that alters any
golden must update the golden in the same PR with an explanation
(IMPLEMENTATION §5).
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import uuid4

from manzil_shared.models import (
    FloorPlan,
    MatchOp,
    NonNegotiable,
    OptionMatch,
    RubricCriterion,
    RubricOption,
)
from manzil_shared.scoring.engine import score, select_display_score

HUNT_ID = uuid4()


def opt(op: MatchOp, value: Any, delta: float, dealbreaker: float | None = None) -> RubricOption:
    return RubricOption(
        match=OptionMatch(op=op, value=value), delta=delta, dealbreaker_set_score=dealbreaker
    )


def crit(
    key: str,
    options: list[RubricOption],
    unknown_delta: float = 0.0,
    non_negotiable: float | None = None,
    enabled: bool = True,
) -> RubricCriterion:
    return RubricCriterion(
        hunt_id=HUNT_ID,
        catalog_key=key,
        options=options,
        unknown_delta=unknown_delta,
        non_negotiable=NonNegotiable(set_score=non_negotiable)
        if non_negotiable is not None
        else None,
        enabled=enabled,
    )


BEDS = crit("beds", [opt(MatchOp.EQ, 2, 0.5), opt(MatchOp.EQ, 1, 0.0), opt(MatchOp.EQ, 0, -0.5)])
LAUNDRY = crit(
    "in_unit_laundry",
    [opt(MatchOp.EQ, "in_unit", 1.0), opt(MatchOp.EQ, "none", -1.0)],
    unknown_delta=-1.0,
)


def test_delta_pass_exact_breakdown() -> None:
    breakdown = score([BEDS, LAUNDRY], {"beds": 2, "in_unit_laundry": "in_unit"}, rubric_version=1)
    assert breakdown.to_contract() == {
        "base": 10.0,
        "total": 11.5,
        "rubric_version": 1,
        "clamped": False,
        "gates": [],
        "criteria": [
            {"key": "beds", "value": 2, "matched": {"op": "eq", "value": 2}, "delta": 0.5},
            {
                "key": "in_unit_laundry",
                "value": "in_unit",
                "matched": {"op": "eq", "value": "in_unit"},
                "delta": 1.0,
            },
        ],
    }


def test_unknown_value_takes_unknown_delta_and_is_marked() -> None:
    breakdown = score([BEDS, LAUNDRY], {"beds": 2}, rubric_version=4)
    assert breakdown.to_contract() == {
        "base": 10.0,
        "total": 9.5,
        "rubric_version": 4,
        "clamped": False,
        "gates": [],
        "criteria": [
            {"key": "beds", "value": 2, "matched": {"op": "eq", "value": 2}, "delta": 0.5},
            {
                "key": "in_unit_laundry",
                "value": None,
                "matched": None,
                "delta": -1.0,
                "unknown": True,
            },
        ],
    }


def test_known_but_unmatched_value_contributes_zero() -> None:
    breakdown = score([BEDS], {"beds": 3}, rubric_version=1)  # no option for 3
    assert breakdown.to_contract()["criteria"] == [
        {"key": "beds", "value": 3, "matched": None, "delta": 0.0}
    ]
    assert breakdown.total == 10.0


def test_first_match_wins_on_overlapping_options() -> None:
    overlapping = crit("sqft", [opt(MatchOp.GT, 700, 0.5), opt(MatchOp.GT, 900, 1.0)])
    breakdown = score([overlapping], {"sqft": 950}, rubric_version=1)
    assert breakdown.criteria[0].delta == 0.5  # first option matched, second never reached


def test_dealbreaker_caps_total_and_populates_informational_criteria() -> None:
    pets = crit(
        "pets_policy",
        [opt(MatchOp.EQ, "cats_and_dogs", 0.5), opt(MatchOp.EQ, "none", 0.0, dealbreaker=0.0)],
    )
    breakdown = score([BEDS, pets], {"beds": 2, "pets_policy": "none"}, rubric_version=2)
    assert breakdown.to_contract() == {
        "base": 10.0,
        "total": 0.0,
        "rubric_version": 2,
        "clamped": False,
        "gates": [
            {
                "key": "pets_policy",
                "kind": "dealbreaker",
                "set_score": 0.0,
                "value": "none",
                "matched": {"op": "eq", "value": "none"},
            }
        ],
        "criteria": [
            {"key": "beds", "value": 2, "matched": {"op": "eq", "value": 2}, "delta": 0.5},
            {
                "key": "pets_policy",
                "value": "none",
                "matched": {"op": "eq", "value": "none"},
                "delta": 0.0,
            },
        ],
    }


def test_non_negotiable_fires_on_negative_match_unmatched_and_unknown() -> None:
    laundry_gate = crit(
        "in_unit_laundry",
        [opt(MatchOp.EQ, "in_unit", 1.0), opt(MatchOp.EQ, "on_site", -0.5)],
        non_negotiable=0.0,
    )
    on_site = score([laundry_gate], {"in_unit_laundry": "on_site"}, rubric_version=1)
    assert on_site.to_contract()["gates"] == [
        {
            "key": "in_unit_laundry",
            "kind": "non_negotiable",
            "set_score": 0.0,
            "value": "on_site",
            "matched": {"op": "eq", "value": "on_site"},
        }
    ]
    assert on_site.total == 0.0
    assert on_site.criteria[0].delta == -0.5

    hookups = score([laundry_gate], {"in_unit_laundry": "hookups"}, rubric_version=1)
    assert hookups.to_contract()["gates"] == [
        {
            "key": "in_unit_laundry",
            "kind": "non_negotiable",
            "set_score": 0.0,
            "value": "hookups",
            "matched": None,
        }
    ]
    assert hookups.criteria[0].delta == 0.0

    unknown = score([laundry_gate], {}, rubric_version=1)
    assert unknown.to_contract()["gates"] == [
        {
            "key": "in_unit_laundry",
            "kind": "non_negotiable",
            "set_score": 0.0,
            "value": None,
            "matched": None,
        }
    ]
    assert unknown.criteria[0].unknown is True


def test_non_negotiable_satisfied_by_acceptable_match() -> None:
    laundry_gate = crit("in_unit_laundry", [opt(MatchOp.EQ, "in_unit", 1.0)], non_negotiable=0.0)
    breakdown = score([laundry_gate], {"in_unit_laundry": "in_unit"}, rubric_version=1)
    assert breakdown.gates == []
    assert breakdown.total == 11.0


def test_advertised_unconfirmed_never_satisfies_non_negotiable() -> None:
    laundry_gate = crit(
        "in_unit_laundry",
        [opt(MatchOp.EQ, "advertised_unconfirmed", 0.0)],
        non_negotiable=2.0,
    )
    breakdown = score(
        [laundry_gate],
        {"in_unit_laundry": "advertised_unconfirmed"},
        rubric_version=1,
    )
    assert [gate.model_dump(mode="json") for gate in breakdown.gates] == [
        {
            "key": "in_unit_laundry",
            "kind": "non_negotiable",
            "set_score": 2.0,
            "value": "advertised_unconfirmed",
            "matched": {"op": "eq", "value": "advertised_unconfirmed"},
        }
    ]
    assert len(breakdown.criteria) == 1


def test_multiple_gates_take_min_never_average() -> None:
    g1 = crit("beds", [opt(MatchOp.EQ, 0, 0.0, dealbreaker=2.0)])
    g2 = crit("pets_policy", [opt(MatchOp.EQ, "cats_only", 0.5)], non_negotiable=1.0)
    breakdown = score([g1, g2], {"beds": 0, "pets_policy": "none"}, rubric_version=3)
    assert breakdown.total == 1.0  # min(2.0, 1.0)
    assert [g.kind for g in breakdown.gates] == ["dealbreaker", "non_negotiable"]
    assert len(breakdown.criteria) == 2


def test_bonus_rubric_exceeds_ten_and_clamps_at_fifteen() -> None:
    bonuses = [
        crit(f"bonus_{i}", [opt(MatchOp.BOOL, True, 2.0)], unknown_delta=0.0) for i in range(4)
    ]
    values = {f"bonus_{i}": True for i in range(4)}
    breakdown = score(bonuses, values, rubric_version=1)  # 10 + 8 = 18 -> clamp
    assert breakdown.total == 15.0
    assert breakdown.clamped is True

    two = score(bonuses[:2], {f"bonus_{i}": True for i in range(2)}, rubric_version=1)
    assert two.total == 14.0  # bonuses may exceed 10 without clamping
    assert two.clamped is False


def test_clamps_at_zero() -> None:
    harsh = [crit(f"c{i}", [opt(MatchOp.BOOL, True, -4.0)]) for i in range(3)]
    breakdown = score(harsh, {f"c{i}": True for i in range(3)}, rubric_version=1)
    assert breakdown.total == 0.0
    assert breakdown.clamped is True


def test_disabled_criterion_is_skipped_entirely() -> None:
    disabled = crit("beds", [opt(MatchOp.EQ, 2, 0.5)], enabled=False)
    breakdown = score([disabled], {"beds": 2}, rubric_version=1)
    assert breakdown.criteria == []
    assert breakdown.total == 10.0


def test_object_value_compares_on_rating() -> None:
    reviews = crit(
        "management_reviews",
        [opt(MatchOp.GT, 4, 0.5), opt(MatchOp.RANGE, [3, 4], 0.0), opt(MatchOp.LT, 3, -0.5)],
    )
    good = score(
        [reviews],
        {"management_reviews": {"rating": 4.6, "summary": "responsive"}},
        rubric_version=1,
    )
    assert good.criteria[0].delta == 0.5
    bad = score(
        [reviews], {"management_reviews": {"rating": 2.1, "summary": "slow"}}, rubric_version=1
    )
    assert bad.criteria[0].delta == -0.5


def test_range_is_inclusive_and_date_strings_order() -> None:
    lease = crit("min_lease_months", [opt(MatchOp.RANGE, [6, 12], 0.5)])
    assert score([lease], {"min_lease_months": 12}, rubric_version=1).criteria[0].delta == 0.5
    avail = crit("availability_date", [opt(MatchOp.LT, "2026-09-01", 0.5)])
    breakdown = score([avail], {"availability_date": "2026-08-15"}, rubric_version=1)
    assert breakdown.criteria[0].delta == 0.5


def test_one_sided_inclusive_comparisons_include_boundary() -> None:
    monthly = crit(
        "all_in_monthly",
        [opt(MatchOp.LTE, 2000, 0.5), opt(MatchOp.GTE, 2200, -0.5)],
    )
    assert score([monthly], {"all_in_monthly": 2000}, rubric_version=1).criteria[0].delta == 0.5
    assert score([monthly], {"all_in_monthly": 2200}, rubric_version=1).criteria[0].delta == -0.5
    assert score([monthly], {"all_in_monthly": 2100}, rubric_version=1).criteria[0].delta == 0.0

    available = crit("availability_date", [opt(MatchOp.LTE, "2026-09-01", 0.5)])
    assert (
        score([available], {"availability_date": "2026-09-01"}, rubric_version=1).criteria[0].delta
        == 0.5
    )


def test_array_set_matches_are_strict_and_first_match_wins() -> None:
    types = crit(
        "property_types",
        [
            opt(MatchOp.CONTAINS_ALL, ["townhome", "loft"], 1.0),
            opt(MatchOp.CONTAINS_ANY, ["townhome", "duplex"], 0.5),
        ],
    )
    both = score(
        [types],
        {"property_types": ["loft", "townhome", "townhome"]},
        rubric_version=1,
    )
    assert both.to_contract()["criteria"] == [
        {
            "key": "property_types",
            "value": ["loft", "townhome", "townhome"],
            "matched": {"op": "contains_all", "value": ["townhome", "loft"]},
            "delta": 1.0,
        }
    ]

    any_only = score([types], {"property_types": ["apartment", "duplex"]}, rubric_version=1)
    assert any_only.criteria[0].delta == 0.5

    for wrong_shape in ("townhome", {"townhome": True}, 1):
        unmatched = score([types], {"property_types": wrong_shape}, rubric_version=1)
        assert unmatched.criteria[0].delta == 0.0


def test_array_set_match_requires_a_non_empty_configured_set() -> None:
    criterion = crit("property_types", [opt(MatchOp.CONTAINS_ALL, [], 1.0)])
    breakdown = score([criterion], {"property_types": ["apartment"]}, rubric_version=1)
    assert breakdown.criteria[0].matched is None
    assert breakdown.total == 10.0


def test_floor_plan_unit_types_overlay_generalized_values() -> None:
    plan = FloorPlan(
        property_id=uuid4(),
        source_id=uuid4(),
        plan_name="Loft A",
        beds=1,
        baths=1,
        unit_types=["loft"],
    )
    unit_types = crit("unit_types", [opt(MatchOp.CONTAINS_ANY, ["loft"], 0.5)])
    breakdown = score([unit_types], {"unit_types": ["apartment"]}, plan, rubric_version=1)
    assert breakdown.criteria[0].value == ["loft"]
    assert breakdown.total == 10.5


def test_multi_plan_group_scores_independently_best_displayed() -> None:
    """§9.4: each floor plan scored independently; group displays best unless pinned."""

    def plan(name: str, beds: int, sqft: int) -> FloorPlan:
        return FloorPlan(
            property_id=uuid4(),
            source_id=uuid4(),
            plan_name=name,
            beds=beds,
            baths=1.0,
            sqft_min=sqft,
            availability_date=date(2026, 9, 1),
        )

    sqft_crit = crit("sqft", [opt(MatchOp.GT, 900, 0.5), opt(MatchOp.LT, 700, -0.5)])
    rubric = [BEDS, sqft_crit]
    shared_values = {"beds": 1}  # property-level value, overlaid per plan

    plans = [plan("A1", 1, 650), plan("B2", 2, 950)]
    breakdowns = [score(rubric, shared_values, p, rubric_version=1) for p in plans]
    assert breakdowns[0].total == 9.5  # beds 1 (+0.0), sqft 650 (-0.5)
    assert breakdowns[1].total == 11.0  # beds 2 (+0.5) from plan overlay, sqft 950 (+0.5)

    assert select_display_score(breakdowns) == 1  # best wins
    assert select_display_score(breakdowns, pinned=0) == 0  # pin overrides best (§9.4)


def test_year_built_range_and_gte_options() -> None:
    year_built = crit(
        "year_built",
        [
            opt(MatchOp.GTE, 2010, 0.5),
            opt(MatchOp.RANGE, [2000, 2009], 0.25),
            opt(MatchOp.LT, 1990, -0.25),
        ],
    )
    assert score([year_built], {"year_built": 2015}, rubric_version=1).criteria[0].delta == 0.5
    assert score([year_built], {"year_built": 2005}, rubric_version=1).criteria[0].delta == 0.25
    assert score([year_built], {"year_built": 1985}, rubric_version=1).criteria[0].delta == -0.25


def test_is_renovated_presence_enum() -> None:
    renovated = crit(
        "is_renovated",
        [
            opt(MatchOp.EQ, "confirmed", 0.25),
            opt(MatchOp.EQ, "advertised_unconfirmed", 0.0),
            opt(MatchOp.EQ, "none", 0.0),
        ],
    )
    assert (
        score([renovated], {"is_renovated": "confirmed"}, rubric_version=1).criteria[0].delta
        == 0.25
    )
    assert (
        score(
            [renovated],
            {"is_renovated": "advertised_unconfirmed"},
            rubric_version=1,
        )
        .criteria[0]
        .delta
        == 0.0
    )
