"""P0-10: SCORE stage assembly — single-source reconciliation, the Phase 0
all_in_monthly interim (conservative advertised rent), per-plan fan-out, and
best-plan display selection (§9.3-9.4)."""

from __future__ import annotations

import asyncio

from conftest import fe, make_state
from manzil_shared.models import Confidence
from manzil_worker.phase0_rubric import PHASE0_RUBRIC_VERSION, phase0_rubric
from manzil_worker.stages.base import StageCtx
from manzil_worker.stages.score import score_stage
from manzil_worker.state import FloorPlanIn


def make_ctx() -> StageCtx:
    return StageCtx(rubric=phase0_rubric(), rubric_version=PHASE0_RUBRIC_VERSION)


def seeded_state():  # type: ignore[no-untyped-def]
    state = make_state()
    state.extractions = {
        "beds": [fe(2, "2 bed")],
        "in_unit_laundry": [fe("in_unit", "washer and dryer in unit")],
        "pets_policy": [fe("cats_and_dogs", "cats and dogs welcome")],
        "patio_balcony": [fe(True, "private balcony")],
    }
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
    assert state.reconciled["beds"].value == 2
    assert state.effective_values["beds"] == 2
    assert "sqft" not in state.effective_values  # unknowns stay absent, not None


def test_low_confidence_value_scores_as_unknown_and_fires_its_gate() -> None:
    """§9.3 + hunt settings v2.3 (`min_confidence`, default medium): a
    VERIFY-demoted value cannot pass a gate — suspect data scores as unknown
    while the value itself stays on `reconciled` as provenance."""
    state = seeded_state()
    state.extractions["pets_policy"] = [
        fe("cats_and_dogs", "cats and dogs welcome", confidence=Confidence.LOW)
    ]
    state.floor_plans = [
        FloorPlanIn(plan_name="A", beds=2, baths=1.0, rent_min=1700.0, rent_max=1750.0)
    ]
    state = asyncio.run(score_stage(state, make_ctx()))

    assert "pets_policy" not in state.effective_values  # thresholded out
    assert state.reconciled["pets_policy"].value == "cats_and_dogs"  # provenance kept
    breakdown = state.scores[0].breakdown
    assert {"key": "pets_policy", "kind": "non_negotiable", "set_score": 2.0} in breakdown["gates"]


def test_min_confidence_low_admits_demoted_values() -> None:
    state = seeded_state()
    state.extractions["pets_policy"] = [
        fe("cats_and_dogs", "cats and dogs welcome", confidence=Confidence.LOW)
    ]
    state.floor_plans = [
        FloorPlanIn(plan_name="A", beds=2, baths=1.0, rent_min=1700.0, rent_max=1750.0)
    ]
    ctx = make_ctx()
    ctx.min_confidence = Confidence.LOW
    state = asyncio.run(score_stage(state, ctx))

    assert state.effective_values["pets_policy"] == "cats_and_dogs"
    assert state.scores[0].breakdown["gates"] == []
    assert state.scores[0].breakdown["total"] == 13.5
