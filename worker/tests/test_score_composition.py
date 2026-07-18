"""P3-9: SCORE composes the full §9.5 all-in through the baselines seam —
metro from the DEDUPE geocode, blocks from EXTRACT, strict-unknown wiring into
the engine, and the display plan's composition landing on RunState."""

from __future__ import annotations

import asyncio
from uuid import uuid4

from manzil_shared.models import MatchOp, OptionMatch, RubricCriterion, RubricOption
from manzil_worker.stages.base import StageCtx
from manzil_worker.stages.score import score_stage
from manzil_worker.state import (
    FloorPlanIn,
    GeocodeIn,
    HeatingIn,
    MandatoryFeeIn,
    MandatoryFeesIn,
    UtilitiesIn,
)
from worker_helpers import make_state

BASELINES = {
    "electric": (120.0, 80.0),
    "electric_heat": (220.0, 140.0),
    "gas_heat": (150.0, 90.0),
    "water": (55.0, 40.0),
    "sewer": (45.0, 35.0),
    "trash": (30.0, 25.0),
}

# One gate-free all_in criterion so the composed value is visible in the
# breakdown without the phase0 rubric's other gates firing on unknowns.
ALL_IN_RUBRIC = [
    RubricCriterion(
        hunt_id=uuid4(),
        catalog_key="all_in_monthly",
        options=[
            RubricOption(match=OptionMatch(op=MatchOp.LT, value=2500), delta=0.5),
            RubricOption(match=OptionMatch(op=MatchOp.GT, value=2500), delta=-0.5),
        ],
        unknown_delta=-1.0,
        position=0,
    )
]


def _state():  # type: ignore[no-untyped-def]
    state = make_state()
    state.geocode = GeocodeIn(place_id="x", lat=42.3, lng=-83.0, city="Canton")
    state.floor_plans = [FloorPlanIn(plan_name="2x2", beds=2, baths=2.0, rent_max=1500.0)]
    state.utilities = UtilitiesIn(included=[])
    state.heating = HeatingIn(heating="gas")
    state.mandatory_fees = MandatoryFeesIn(
        fees=[MandatoryFeeIn(name="valet trash", amount_monthly=25.0)]
    )
    return state


def _ctx(baselines):  # type: ignore[no-untyped-def]
    async def lookup(metro: str, bucket: int):  # type: ignore[no-untyped-def]
        assert metro == "Canton" and bucket == 2
        return baselines

    return StageCtx(rubric=ALL_IN_RUBRIC, utility_baselines_lookup=lookup)


def _all_in_entry(state):  # type: ignore[no-untyped-def]
    breakdown = state.scores[state.display_score_index].breakdown
    return next(c for c in breakdown["criteria"] if c["key"] == "all_in_monthly")


def test_score_composes_full_all_in_through_the_seam() -> None:
    state = asyncio.run(score_stage(_state(), _ctx(BASELINES)))
    # rent 1500 + valet trash fee 25 + electric 120 + gas_heat 150 + water 55 +
    # sewer 45 (trash estimate suppressed by the billed fee) = 1895
    entry = _all_in_entry(state)
    assert entry["value"] == 1895.0
    assert state.all_in_components is not None
    assert state.all_in_components["total"] == 1895.0
    assert state.all_in_components["estimated_total"] == 370.0
    assert state.all_in_components["badges"] == []


def test_each_plan_carries_its_own_composition() -> None:
    """P3-9 follow-up: the cell/drawer render per-plan compositions, so every
    PlanScore must carry the composition of ITS rent — not the display plan's."""
    state = _state()
    state.floor_plans = [
        FloorPlanIn(plan_name="1x1", beds=1, baths=1.0, rent_max=1069.0),
        FloorPlanIn(plan_name="2x1", beds=2, baths=1.0, rent_max=1179.0),
    ]

    async def lookup(metro: str, bucket: int):  # type: ignore[no-untyped-def]
        return BASELINES

    ctx = StageCtx(rubric=ALL_IN_RUBRIC, utility_baselines_lookup=lookup)
    state = asyncio.run(score_stage(state, ctx))
    assert all(s.all_in_components is not None for s in state.scores)
    rents = [
        next(c["amount"] for c in s.all_in_components["components"] if c["name"] == "rent")
        for s in state.scores
    ]
    assert rents == [1069.0, 1179.0]
    # Each plan composes with its own rent + fee 25 + estimates 370.
    assert [s.all_in_components["total"] for s in state.scores] == [1464.0, 1574.0]


def test_missing_baseline_row_scores_unknown_delta() -> None:
    partial = {k: v for k, v in BASELINES.items() if k != "sewer"}
    state = asyncio.run(score_stage(_state(), _ctx(partial)))
    entry = _all_in_entry(state)
    assert entry.get("unknown") is True
    assert entry["delta"] == -1.0  # unknown_delta, never a fabricated number
    assert state.all_in_components is not None
    assert state.all_in_components["total"] is None
    assert "fees_unverified" in state.all_in_components["badges"]


def test_no_metro_baselines_keeps_the_v1_slice() -> None:
    async def none_lookup(metro: str, bucket: int):  # type: ignore[no-untyped-def]
        return None

    state = _state()
    ctx = StageCtx(rubric=ALL_IN_RUBRIC, utility_baselines_lookup=none_lookup)
    state = asyncio.run(score_stage(state, ctx))
    entry = _all_in_entry(state)
    assert entry["value"] == 1525.0  # rent + fee, no utility estimates
    assert "utilities_not_estimated" in (state.all_in_components or {})["badges"]


def test_no_geocode_means_no_metro_and_v1_fallback() -> None:
    state = _state()
    state.geocode = None

    async def boom(metro: str, bucket: int):  # type: ignore[no-untyped-def]
        raise AssertionError("no metro → the seam must not be called")

    ctx = StageCtx(rubric=ALL_IN_RUBRIC, utility_baselines_lookup=boom)
    state = asyncio.run(score_stage(state, ctx))
    assert _all_in_entry(state)["value"] == 1525.0
