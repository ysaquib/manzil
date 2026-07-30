"""The hardcoded Phase 0 rubric (DESIGN §19): Yusuf's real criteria, checked
in as a fixture — 2 br, in-unit laundry, balcony, cats allowed, all-in <
$2,000 conservative. Real hunts build rubrics in the UI from Phase 1; this
one exists so the CLI pipeline scores real listings during Phase 0 and the
eval harness (P0-12) has a stable rubric to run under.

Rubric version 0 is reserved for this fixture.
"""

from __future__ import annotations

from uuid import UUID

from manzil_shared.models import (
    MatchOp,
    NonNegotiable,
    OptionMatch,
    RubricCriterion,
    RubricOption,
)

PHASE0_HUNT_ID = UUID(int=0)
PHASE0_RUBRIC_VERSION = 0


def _opt(op: MatchOp, value: object, delta: float) -> RubricOption:
    return RubricOption(match=OptionMatch(op=op, value=value), delta=delta)


def phase0_rubric() -> list[RubricCriterion]:
    return [
        # 2 bedrooms, non-negotiable: only beds == 2 is acceptable (delta >= 0);
        # any other known value matches no option -> gate fires; unknown fires too.
        RubricCriterion(
            hunt_id=PHASE0_HUNT_ID,
            catalog_key="beds",
            options=[_opt(MatchOp.EQ, 2, 0.5)],
            non_negotiable=NonNegotiable(set_score=2.0),
            position=0,
        ),
        # In-unit laundry, non-negotiable: in_unit is the only acceptable option.
        RubricCriterion(
            hunt_id=PHASE0_HUNT_ID,
            catalog_key="in_unit_laundry",
            options=[
                _opt(MatchOp.CONTAINS_ANY, ["in_unit"], 1.0),
                _opt(MatchOp.CONTAINS_ANY, ["hookups"], -0.25),
                _opt(MatchOp.CONTAINS_ANY, ["on_site"], -0.5),
                _opt(MatchOp.CONTAINS_ANY, ["none"], -1.0),
                _opt(MatchOp.CONTAINS_ANY, ["advertised_unconfirmed"], -1.0),
            ],
            non_negotiable=NonNegotiable(set_score=2.0),
            position=1,
        ),
        # Cats allowed, non-negotiable.
        RubricCriterion(
            hunt_id=PHASE0_HUNT_ID,
            catalog_key="pets_policy",
            options=[
                _opt(MatchOp.EQ, "cats_and_dogs", 0.5),
                _opt(MatchOp.EQ, "cats_only", 0.25),
                _opt(MatchOp.EQ, "dogs_only", -0.5),
                _opt(MatchOp.EQ, "none", -0.5),
            ],
            non_negotiable=NonNegotiable(set_score=2.0),
            position=2,
        ),
        # Balcony or patio: wanted, not gated.
        RubricCriterion(
            hunt_id=PHASE0_HUNT_ID,
            catalog_key="patio_balcony",
            options=[
                _opt(MatchOp.EQ, "confirmed", 0.5),
                _opt(MatchOp.EQ, "advertised_unconfirmed", 0.0),
                _opt(MatchOp.EQ, "none", 0.0),
            ],
            position=3,
        ),
        # All-in monthly < $2,000 conservative, non-negotiable. Composed by the
        # pipeline (Phase 0: conservative advertised rent; full §9.5 lands P3-9).
        RubricCriterion(
            hunt_id=PHASE0_HUNT_ID,
            catalog_key="all_in_monthly",
            options=[
                _opt(MatchOp.LT, 1800, 1.0),
                _opt(MatchOp.RANGE, [1800, 2000], 0.5),
                _opt(MatchOp.GT, 2000, -1.0),
            ],
            non_negotiable=NonNegotiable(set_score=3.0),
            position=4,
        ),
    ]
