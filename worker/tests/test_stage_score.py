"""P0-10: SCORE stage assembly — single-source reconciliation, the Phase 0
all_in_monthly interim (conservative advertised rent), per-plan fan-out, and
best-plan display selection (§9.3-9.4)."""

from __future__ import annotations

import asyncio

from manzil_shared.models import Confidence
from manzil_worker.phase0_rubric import PHASE0_RUBRIC_VERSION, phase0_rubric
from manzil_worker.stages.base import StageCtx
from manzil_worker.stages.score import score_stage
from manzil_worker.state import FloorPlanIn, PetCostsIn
from worker_helpers import fe, get_claim, make_state, set_claim


def _all_in(breakdown: dict) -> float | None:  # type: ignore[type-arg]
    entry = next(c for c in breakdown["criteria"] if c["key"] == "all_in_monthly")
    return entry["value"]


def make_ctx() -> StageCtx:
    return StageCtx(rubric=phase0_rubric(), rubric_version=PHASE0_RUBRIC_VERSION)


def seeded_state():  # type: ignore[no-untyped-def]
    state = make_state()
    set_claim(state, "beds", fe(2, "2 bed"))
    set_claim(state, "in_unit_laundry", fe("in_unit", "washer and dryer in unit"))
    set_claim(state, "pets_policy", fe("cats_and_dogs", "cats and dogs welcome"))
    set_claim(state, "patio_balcony", fe(True, "private balcony"))
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
    assert premium["gates"] == [
        {"key": "all_in_monthly", "kind": "non_negotiable", "set_score": 3.0}
    ]
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
    assert {"key": "all_in_monthly", "kind": "non_negotiable", "set_score": 3.0} in breakdown[
        "gates"
    ]


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
    assert {"key": "pets_policy", "kind": "non_negotiable", "set_score": 2.0} in breakdown["gates"]


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
