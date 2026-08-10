from __future__ import annotations

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
from manzil_shared.scoped_facts import (
    EffectiveFact,
    ScopedValue,
    resolve_effective_facts,
    scoring_values_for_policy,
)
from manzil_shared.scoring.engine import score


def _gallery() -> EffectiveFact:
    return EffectiveFact(
        value=4,
        target_scope=TargetScope.PROPERTY,
        applicability=UnitApplicability.UNIT_SCOPE_UNSPECIFIED,
        origin_key="vision:model",
        resolution_rule="vision_weighted_median_gallery",
    )


def test_all_generalized_vision_policies() -> None:
    facts = {"kitchen_quality": _gallery()}
    assert scoring_values_for_policy(facts, "full_rubric") == (
        {"kitchen_quality": 4},
        {"kitchen_quality": 4},
    )
    assert scoring_values_for_policy(facts, "points_only") == (
        {"kitchen_quality": 4},
        {},
    )
    assert scoring_values_for_policy(facts, "unknown") == ({}, {})


def test_exact_vision_is_never_suppressed() -> None:
    exact = EffectiveFact(
        value=5,
        target_scope=TargetScope.FLOOR_PLAN,
        applicability=UnitApplicability.SPECIFIC_FLOOR_PLANS,
        origin_key="vision:model",
        resolution_rule="vision_weighted_median_exact",
    )
    assert scoring_values_for_policy({"kitchen_quality": exact}, "unknown") == (
        {"kitchen_quality": 5},
        {"kitchen_quality": 5},
    )


def test_low_confidence_vision_scores_points_but_never_enters_gate_values() -> None:
    exact = EffectiveFact(
        value=3,
        target_scope=TargetScope.FLOOR_PLAN,
        applicability=UnitApplicability.SPECIFIC_FLOOR_PLANS,
        origin_key="vision:model",
        resolution_rule="vision_weighted_median_exact",
        confidence=Confidence.LOW,
    )
    gallery = EffectiveFact(
        value=4,
        target_scope=TargetScope.PROPERTY,
        applicability=UnitApplicability.UNIT_SCOPE_UNSPECIFIED,
        origin_key="vision:model",
        resolution_rule="vision_weighted_median_gallery",
        confidence=Confidence.LOW,
    )
    assert scoring_values_for_policy({"exact": exact, "gallery": gallery}, "full_rubric") == (
        {"exact": 3, "gallery": 4},
        {},
    )

    criterion = RubricCriterion(
        hunt_id=uuid4(),
        catalog_key="exact",
        options=[
            RubricOption(
                match=OptionMatch(op=MatchOp.EQ, value=3),
                delta=1.0,
            )
        ],
        non_negotiable=NonNegotiable(set_score=2.0),
    )
    points, gates = scoring_values_for_policy({"exact": exact}, "full_rubric")
    breakdown = score(
        [criterion],
        points,
        rubric_version=1,
        gate_values=gates,
    )
    assert breakdown.total == 2.0
    assert breakdown.gates[0].key == "exact"
    assert breakdown.gates[0].value is None
    assert breakdown.gates[0].matched is None
    assert breakdown.criteria[0].delta == 1.0
    assert breakdown.criteria[0].value == 3


def test_vision_uses_its_own_low_default_threshold() -> None:
    facts = resolve_effective_facts(
        criterion_keys=["kitchen_quality", "pets_policy"],
        floor_plan_id=None,
        extractions=[
            ScopedValue(
                criterion_key="kitchen_quality",
                value=3,
                confidence=Confidence.LOW,
                applicability=UnitApplicability.UNIT_SCOPE_UNSPECIFIED,
                origin_key="vision:model",
                resolution_rule="vision_weighted_median_gallery",
            ),
            ScopedValue(
                criterion_key="pets_policy",
                value="cats_and_dogs",
                confidence=Confidence.LOW,
            ),
        ],
        min_confidence=Confidence.MEDIUM,
        min_vision_confidence=Confidence.LOW,
    )
    assert set(facts) == {"kitchen_quality"}
    assert facts["kitchen_quality"].confidence is Confidence.LOW


def test_medium_vision_confidence_can_enter_gate_values() -> None:
    exact = EffectiveFact(
        value=5,
        target_scope=TargetScope.FLOOR_PLAN,
        applicability=UnitApplicability.SPECIFIC_FLOOR_PLANS,
        origin_key="vision:model",
        resolution_rule="vision_weighted_median_exact",
        confidence=Confidence.MEDIUM,
    )
    assert scoring_values_for_policy({"kitchen_quality": exact}, "full_rubric") == (
        {"kitchen_quality": 5},
        {"kitchen_quality": 5},
    )
