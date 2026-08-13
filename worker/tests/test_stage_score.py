"""P0-10: SCORE stage assembly — single-source reconciliation, the Phase 0
all_in_monthly interim (conservative advertised rent), per-plan fan-out, and
best-plan display selection (§9.3-9.4)."""

from __future__ import annotations

import asyncio
from uuid import uuid4

from manzil_shared.models import (
    Confidence,
    MatchOp,
    NonNegotiable,
    OptionMatch,
    RubricCriterion,
    RubricOption,
    TargetScope,
    UnitApplicability,
)
from manzil_worker.phase0_rubric import PHASE0_RUBRIC_VERSION, phase0_rubric
from manzil_worker.stages.base import StageCtx
from manzil_worker.stages.score import score_stage
from manzil_worker.state import FloorPlanIn, PetCostsIn, SourceClaim
from worker_helpers import all_units_fe, fe, get_claim, make_state, set_claim


def _all_in(breakdown: dict) -> float | None:  # type: ignore[type-arg]
    entry = next(c for c in breakdown["criteria"] if c["key"] == "all_in_monthly")
    return entry["value"]


def _gate(gates: list[dict[str, object]], *, key: str, kind: str) -> dict[str, object]:
    return next(g for g in gates if g["key"] == key and g["kind"] == kind)


def make_ctx() -> StageCtx:
    return StageCtx(rubric=phase0_rubric(), rubric_version=PHASE0_RUBRIC_VERSION)


def seeded_state():  # type: ignore[no-untyped-def]
    state = make_state()
    set_claim(state, "beds", fe(2, "2 bed"))
    set_claim(state, "in_unit_laundry", all_units_fe("in_unit", "washer and dryer in every home"))
    set_claim(state, "pets_policy", fe("cats_and_dogs", "cats and dogs welcome"))
    set_claim(state, "patio_balcony", all_units_fe(True, "private balcony in every home"))
    return state


def test_each_plan_scores_independently_and_best_plan_is_display() -> None:
    state = seeded_state()
    state.floor_plans = [
        FloorPlanIn(plan_name="Affordable", beds=2, baths=1.0, rent_min=1700.0, rent_max=1750.0),
        FloorPlanIn(plan_name="Premium", beds=2, baths=2.0, rent_min=2050.0, rent_max=2100.0),
    ]
    state = asyncio.run(score_stage(state, make_ctx()))

    assert [s.plan_name for s in state.scores] == ["Affordable", "Premium"]
    affordable, premium = (s.breakdown for s in state.scores)
    # Affordable: base 10 + beds .5 + laundry 1 + cats .5 + balcony .5 + all-in(<1800) 1
    assert affordable["total"] == 13.5
    assert affordable["gates"] == []
    # Premium: conservative rent 2100 > 2000 -> the all-in non-negotiable fires.
    premium_gate = _gate(premium["gates"], key="all_in_monthly", kind="non_negotiable")
    assert premium_gate["set_score"] == 3.0
    assert premium_gate["value"] == 2100.0
    assert premium_gate["matched"] == {"op": "gt", "value": 2000}
    assert premium["total"] == 3.0
    assert state.display_score_index == 0  # best plan displays (§9.4)


def test_all_in_composition_uses_rent_max_never_the_teaser_rate() -> None:
    state = seeded_state()
    state.floor_plans = [
        # Teaser $1,795 but worst realistic month $2,050: must gate, not pass.
        FloorPlanIn(plan_name="Teaser", beds=2, baths=1.0, rent_min=1795.0, rent_max=2050.0)
    ]
    state = asyncio.run(score_stage(state, make_ctx()))
    assert state.scores[0].breakdown["gates"] != []


def test_no_plans_scores_once_property_level_with_all_in_unknown() -> None:
    state = seeded_state()
    state = asyncio.run(score_stage(state, make_ctx()))

    assert len(state.scores) == 1
    assert state.scores[0].plan_name is None
    breakdown = state.scores[0].breakdown
    # all_in_monthly unknown -> its non-negotiable fires (unknown never passes a gate).
    gate = _gate(breakdown["gates"], key="all_in_monthly", kind="non_negotiable")
    assert gate["set_score"] == 3.0
    assert gate["value"] is None
    assert gate["matched"] is None


def test_reconciled_and_effective_values_are_recorded() -> None:
    state = seeded_state()
    state = asyncio.run(score_stage(state, make_ctx()))
    assert get_claim(state, "beds").value == 2
    assert state.effective_values["beds"] == 2
    assert "sqft" not in state.effective_values  # unknowns stay absent, not None


def test_low_confidence_value_scores_as_unknown_and_fires_its_gate() -> None:
    """§9.3 + hunt settings v2.3 (`min_confidence`, default medium): a
    VERIFY-demoted value cannot pass a gate — suspect data scores as unknown
    while the value itself stays on `reconciled` as provenance."""
    state = seeded_state()
    set_claim(
        state,
        "pets_policy",
        fe("cats_and_dogs", "cats and dogs welcome", confidence=Confidence.LOW),
    )
    state.floor_plans = [
        FloorPlanIn(plan_name="A", beds=2, baths=1.0, rent_min=1700.0, rent_max=1750.0)
    ]
    state = asyncio.run(score_stage(state, make_ctx()))

    assert "pets_policy" not in state.effective_values  # thresholded out
    assert get_claim(state, "pets_policy").value == "cats_and_dogs"  # provenance kept
    breakdown = state.scores[0].breakdown
    gate = _gate(breakdown["gates"], key="pets_policy", kind="non_negotiable")
    assert gate["set_score"] == 2.0
    assert gate["value"] is None
    assert gate["matched"] is None


def _score_with_pets(pet_costs: PetCostsIn | None, *, cats: int, dogs: int, rent: float) -> dict:  # type: ignore[type-arg]
    state = seeded_state()
    state.pet_costs = pet_costs
    state.floor_plans = [
        FloorPlanIn(plan_name="A", beds=2, baths=1.0, rent_min=rent, rent_max=rent)
    ]
    ctx = make_ctx()
    ctx.cats = cats
    ctx.dogs = dogs
    state = asyncio.run(score_stage(state, ctx))
    return state.scores[0].breakdown


def test_all_in_folds_species_specific_pet_rent() -> None:
    # §9.5 v1: 2 cats x $20 + 1 dog x $35 = $75 added to conservative rent.
    breakdown = _score_with_pets(
        PetCostsIn(cat_rent_monthly=20.0, dog_rent_monthly=35.0),
        cats=2,
        dogs=1,
        rent=1700.0,
    )
    assert _all_in(breakdown) == 1775.0


def test_all_in_falls_back_to_generic_pet_rent() -> None:
    # No species-specific rent → the generic per-pet figure applies to each pet.
    breakdown = _score_with_pets(
        PetCostsIn(pet_rent_monthly=30.0),
        cats=1,
        dogs=1,
        rent=1700.0,
    )
    assert _all_in(breakdown) == 1760.0


def test_all_in_unchanged_when_no_pets() -> None:
    breakdown = _score_with_pets(
        PetCostsIn(cat_rent_monthly=20.0, dog_rent_monthly=35.0),
        cats=0,
        dogs=0,
        rent=1700.0,
    )
    assert _all_in(breakdown) == 1700.0


def test_species_with_no_rent_contributes_zero() -> None:
    # Cat rent known, dog rent absent (no specific, no generic) → dog adds 0,
    # the slot stays visibly unfilled rather than being fabricated.
    breakdown = _score_with_pets(
        PetCostsIn(cat_rent_monthly=20.0),
        cats=1,
        dogs=1,
        rent=1700.0,
    )
    assert _all_in(breakdown) == 1720.0


def test_all_in_unchanged_when_pet_costs_absent() -> None:
    breakdown = _score_with_pets(None, cats=1, dogs=1, rent=1700.0)
    assert _all_in(breakdown) == 1700.0


def test_min_confidence_low_admits_demoted_values() -> None:
    state = seeded_state()
    set_claim(
        state,
        "pets_policy",
        fe("cats_and_dogs", "cats and dogs welcome", confidence=Confidence.LOW),
    )
    state.floor_plans = [
        FloorPlanIn(plan_name="A", beds=2, baths=1.0, rent_min=1700.0, rent_max=1750.0)
    ]
    ctx = make_ctx()
    ctx.min_confidence = Confidence.LOW
    state = asyncio.run(score_stage(state, ctx))

    assert state.effective_values["pets_policy"] == "cats_and_dogs"
    assert state.scores[0].breakdown["gates"] == []
    assert state.scores[0].breakdown["total"] == 13.5


def test_low_confidence_vision_is_kept_for_points_but_cannot_pass_gate() -> None:
    state = make_state()
    state.floor_plans = [
        FloorPlanIn(
            response_key="a",
            plan_name="A",
            beds=2,
            baths=1.0,
            rent_min=1700.0,
        )
    ]
    visual = fe(4, "Reference-anchored kitchen", confidence=Confidence.LOW)
    visual.target_scope = TargetScope.FLOOR_PLAN
    visual.floor_plan_ref = "a"
    visual.applicability = UnitApplicability.SPECIFIC_FLOOR_PLANS
    visual.origin_key = "vision:model"
    visual.resolution_rule = "vision_weighted_median_exact"
    set_claim(state, "kitchen_quality", visual)
    criterion = RubricCriterion(
        hunt_id=uuid4(),
        catalog_key="kitchen_quality",
        options=[
            RubricOption(
                match=OptionMatch(op=MatchOp.EQ, value=4),
                delta=1.0,
            )
        ],
        non_negotiable=NonNegotiable(set_score=2.0),
    )
    ctx = StageCtx(rubric=[criterion], rubric_version=1)

    state = asyncio.run(score_stage(state, ctx))

    assert state.effective_values["kitchen_quality"] == 4
    assert state.scores[0].breakdown["total"] == 2.0
    gate = _gate(
        state.scores[0].breakdown["gates"],
        key="kitchen_quality",
        kind="non_negotiable",
    )
    assert gate["set_score"] == 2.0
    assert gate["value"] is None
    assert gate["matched"] is None
    kitchen = next(
        c for c in state.scores[0].breakdown["criteria"] if c["key"] == "kitchen_quality"
    )
    assert kitchen["value"] == 4
    assert kitchen["delta"] == 1.0


def test_exact_unit_feature_changes_only_target_floor_plan() -> None:
    state = seeded_state()
    state.floor_plans = [
        FloorPlanIn(response_key="a", plan_name="A", beds=2, baths=1.0, rent_min=1700.0),
        FloorPlanIn(response_key="b", plan_name="B", beds=2, baths=1.0, rent_min=1700.0),
    ]
    exact = fe(False, "Plan A has no balcony")
    exact.target_scope = TargetScope.FLOOR_PLAN
    exact.floor_plan_ref = "a"
    exact.applicability = UnitApplicability.SPECIFIC_FLOOR_PLANS
    set_claim(state, "patio_balcony", exact)

    state = asyncio.run(score_stage(state, make_ctx()))

    values = [
        next(
            criterion["value"]
            for criterion in score.breakdown["criteria"]
            if criterion["key"] == "patio_balcony"
        )
        for score in state.scores
    ]
    assert values == ["none", None]


def test_sc6_presence_claim_scores_only_its_exact_floor_plan() -> None:
    state = make_state()
    state.floor_plans = [
        FloorPlanIn(response_key="a", plan_name="A", beds=2, baths=1.0, rent_min=1700.0),
        FloorPlanIn(response_key="b", plan_name="B", beds=2, baths=1.0, rent_min=1700.0),
    ]
    exact = fe(True, "Plan A includes a fireplace")
    exact.target_scope = TargetScope.FLOOR_PLAN
    exact.floor_plan_ref = "a"
    exact.applicability = UnitApplicability.SPECIFIC_FLOOR_PLANS
    set_claim(state, "fireplace", exact)
    criterion = RubricCriterion(
        hunt_id=uuid4(),
        catalog_key="fireplace",
        options=[
            RubricOption(
                match=OptionMatch(op=MatchOp.EQ, value="confirmed"),
                delta=0.25,
            )
        ],
    )

    state = asyncio.run(score_stage(state, StageCtx(rubric=[criterion], rubric_version=1)))

    values = [score.breakdown["criteria"][0]["value"] for score in state.scores]
    assert values == ["confirmed", None]
    assert [score.breakdown["total"] for score in state.scores] == [10.25, 10.0]


def test_sc7_flooring_scores_exact_and_all_units_but_not_select_units() -> None:
    criterion = RubricCriterion(
        hunt_id=uuid4(),
        catalog_key="flooring_materials",
        options=[
            RubricOption(
                match=OptionMatch(op=MatchOp.CONTAINS_ANY, value=["hardwood"]),
                delta=1.0,
            )
        ],
        unknown_delta=-1.0,
    )

    def scored(applicability: UnitApplicability) -> tuple[object, float]:
        state = make_state()
        state.floor_plans = [
            FloorPlanIn(response_key="a", plan_name="A", beds=2, baths=1.0, rent_min=1700.0)
        ]
        materials = fe(["hardwood", "tile"], "Hardwood living areas and tile bath")
        materials.applicability = applicability
        if applicability is UnitApplicability.SPECIFIC_FLOOR_PLANS:
            materials.target_scope = TargetScope.FLOOR_PLAN
            materials.floor_plan_ref = "a"
        set_claim(state, "flooring_materials", materials)
        result = asyncio.run(score_stage(state, StageCtx(rubric=[criterion], rubric_version=1)))
        row = result.scores[0].breakdown["criteria"][0]
        return row["value"], result.scores[0].breakdown["total"]

    assert scored(UnitApplicability.SPECIFIC_FLOOR_PLANS) == (["hardwood", "tile"], 11.0)
    assert scored(UnitApplicability.ALL_UNITS) == (["hardwood", "tile"], 11.0)
    assert scored(UnitApplicability.SELECT_UNITS) == (None, 9.0)


def test_unspecified_laundry_cannot_pass_gate() -> None:
    state = seeded_state()
    set_claim(
        state,
        "in_unit_laundry",
        fe("in_unit", "Washer and dryer listed among amenities"),
    )
    claim = get_claim(state, "in_unit_laundry")
    claim.applicability = UnitApplicability.UNIT_SCOPE_UNSPECIFIED
    state.floor_plans = [
        FloorPlanIn(response_key="a", plan_name="A", beds=2, baths=1.0, rent_min=1700.0)
    ]

    state = asyncio.run(score_stage(state, make_ctx()))

    assert state.effective_values["in_unit_laundry"] == ["advertised_unconfirmed"]
    gate = _gate(
        state.scores[0].breakdown["gates"],
        key="in_unit_laundry",
        kind="non_negotiable",
    )
    assert gate["set_score"] == 2.0
    assert gate["value"] == ["advertised_unconfirmed"]
    assert gate["matched"] == {"op": "contains_any", "value": ["advertised_unconfirmed"]}


def test_enrich_grocery_on_resolved_scores_only_when_rubric_includes_it() -> None:
    """ENRICH dual-writes onto resolved_claims; SCORE uses that list. Enabled
    Criteria score; disabled (absent from Rubric) Criteria are omitted."""
    from manzil_shared.catalog import CATALOG

    grocery_entry = next(e for e in CATALOG if e.key == "grocery_proximity")
    grocery_criterion = RubricCriterion(
        hunt_id=uuid4(),
        catalog_key="grocery_proximity",
        options=list(grocery_entry.default_options),
        position=0,
    )
    beds_criterion = RubricCriterion(
        hunt_id=grocery_criterion.hunt_id,
        catalog_key="beds",
        options=[RubricOption(match=OptionMatch(op=MatchOp.EQ, value=2), delta=0.5)],
        position=1,
    )

    grocery = SourceClaim(
        criterion_key="grocery_proximity",
        value=7.5,
        confidence=Confidence.HIGH,
        evidence_quote="Nearest grocery: Kroger — 7.5 min driving (Google Maps)",
        origin_key="google_maps:grocery",
        source_id=None,
        model="maps",
        prompt_version=0,
        resolution_rule="single_source",
    )
    beds = fe(2, "2 bed")
    beds.criterion_key = "beds"
    beds.resolution_rule = "single_source"

    with_grocery = make_state()
    with_grocery.resolved_claims = [beds.model_copy(deep=True), grocery.model_copy(deep=True)]
    scored = asyncio.run(
        score_stage(
            with_grocery,
            StageCtx(rubric=[grocery_criterion, beds_criterion], rubric_version=1),
        )
    )
    keys = {row["key"] for row in scored.scores[0].breakdown["criteria"]}
    assert "grocery_proximity" in keys
    grocery_row = next(
        row for row in scored.scores[0].breakdown["criteria"] if row["key"] == "grocery_proximity"
    )
    assert grocery_row["value"] == 7.5
    assert grocery_row["delta"] == 0.5  # < 10 minutes

    without_grocery = make_state()
    without_grocery.resolved_claims = [beds.model_copy(deep=True), grocery.model_copy(deep=True)]
    omitted = asyncio.run(
        score_stage(without_grocery, StageCtx(rubric=[beds_criterion], rubric_version=1))
    )
    assert "grocery_proximity" not in {
        row["key"] for row in omitted.scores[0].breakdown["criteria"]
    }
