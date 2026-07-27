from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from manzil_shared.models import Confidence, TargetScope, UnitApplicability
from manzil_shared.scoped_facts import (
    ScopedOverrideValue,
    ScopedValue,
    resolve_effective_value,
)

NOW = datetime.now(UTC)


def _resolve(
    *,
    floor_plan_id=None,  # type: ignore[no-untyped-def]
    extractions=(),  # type: ignore[no-untyped-def]
    overrides=(),  # type: ignore[no-untyped-def]
    presence_like: bool = False,
):
    return resolve_effective_value(
        criterion_key="patio_balcony",
        floor_plan_id=floor_plan_id,
        extractions=extractions,
        overrides=overrides,
        min_confidence=Confidence.MEDIUM,
        presence_like=presence_like,
    )


def test_exact_floor_plan_fact_beats_generalized_unit_fact() -> None:
    target = uuid4()
    other = uuid4()
    generalized = ScopedValue(
        criterion_key="patio_balcony",
        value=True,
        target_scope=TargetScope.PROPERTY,
        applicability=UnitApplicability.ALL_UNITS,
        observed_at=NOW,
    )
    exact = ScopedValue(
        criterion_key="patio_balcony",
        value=False,
        target_scope=TargetScope.FLOOR_PLAN,
        floor_plan_id=target,
        applicability=UnitApplicability.SPECIFIC_FLOOR_PLANS,
        observed_at=NOW - timedelta(minutes=1),
    )

    assert _resolve(floor_plan_id=target, extractions=[generalized, exact]) is False
    assert _resolve(floor_plan_id=other, extractions=[generalized, exact]) is True


def test_select_and_unspecified_presence_are_advertised_not_confirmed() -> None:
    for applicability in (
        UnitApplicability.SELECT_UNITS,
        UnitApplicability.UNIT_SCOPE_UNSPECIFIED,
    ):
        row = ScopedValue(
            criterion_key="patio_balcony",
            value=True,
            target_scope=TargetScope.PROPERTY,
            applicability=applicability,
        )
        assert _resolve(extractions=[row], presence_like=True) == "advertised_unconfirmed"


def test_typed_presence_keeps_exact_value_but_generalized_is_unconfirmed() -> None:
    target = uuid4()
    exact = ScopedValue(
        criterion_key="patio_balcony",
        value="central",
        target_scope=TargetScope.FLOOR_PLAN,
        floor_plan_id=target,
        applicability=UnitApplicability.SPECIFIC_FLOOR_PLANS,
    )
    generalized = ScopedValue(
        criterion_key="patio_balcony",
        value="central",
        target_scope=TargetScope.PROPERTY,
        applicability=UnitApplicability.SELECT_UNITS,
    )
    assert (
        resolve_effective_value(
            criterion_key="patio_balcony",
            floor_plan_id=target,
            extractions=[exact],
            min_confidence=Confidence.MEDIUM,
            presence_like=True,
            boolean_presence=False,
        )
        == "central"
    )
    assert (
        resolve_effective_value(
            criterion_key="patio_balcony",
            floor_plan_id=target,
            extractions=[generalized],
            min_confidence=Confidence.MEDIUM,
            presence_like=True,
            boolean_presence=False,
        )
        == "advertised_unconfirmed"
    )


def test_legacy_property_boolean_never_becomes_confirmed_unit_truth() -> None:
    legacy = ScopedValue(
        criterion_key="patio_balcony",
        value=True,
        target_scope=TargetScope.PROPERTY,
        applicability=None,
    )
    assert _resolve(extractions=[legacy], presence_like=True) is None


def test_legacy_property_override_never_becomes_confirmed_unit_truth() -> None:
    legacy = ScopedOverrideValue(
        criterion_key="patio_balcony",
        value=True,
        target_scope=TargetScope.PROPERTY,
        applicability=None,
    )
    assert _resolve(overrides=[legacy], presence_like=True) is None


def test_override_specificity_and_target_local_tombstone() -> None:
    target = uuid4()
    all_units = ScopedOverrideValue(
        criterion_key="patio_balcony",
        value="all",
        target_scope=TargetScope.PROPERTY,
        applicability=UnitApplicability.ALL_UNITS,
        created_at=NOW,
    )
    exact = ScopedOverrideValue(
        criterion_key="patio_balcony",
        value="exact",
        target_scope=TargetScope.FLOOR_PLAN,
        floor_plan_id=target,
        applicability=UnitApplicability.SPECIFIC_FLOOR_PLANS,
        created_at=NOW,
    )
    reverted_exact = ScopedOverrideValue(
        criterion_key="patio_balcony",
        value=None,
        target_scope=TargetScope.FLOOR_PLAN,
        floor_plan_id=target,
        applicability=UnitApplicability.SPECIFIC_FLOOR_PLANS,
        created_at=NOW + timedelta(minutes=1),
    )

    assert _resolve(floor_plan_id=target, overrides=[all_units, exact]) == "exact"
    assert (
        _resolve(
            floor_plan_id=target,
            overrides=[all_units, exact, reverted_exact],
        )
        == "all"
    )


def test_low_confidence_exact_fact_does_not_hide_eligible_generalized_fact() -> None:
    target = uuid4()
    assert (
        _resolve(
            floor_plan_id=target,
            extractions=[
                ScopedValue(
                    criterion_key="patio_balcony",
                    value="generalized",
                    confidence=Confidence.MEDIUM,
                    target_scope=TargetScope.PROPERTY,
                    applicability=UnitApplicability.UNIT_SCOPE_UNSPECIFIED,
                ),
                ScopedValue(
                    criterion_key="patio_balcony",
                    value="exact",
                    confidence=Confidence.LOW,
                    target_scope=TargetScope.FLOOR_PLAN,
                    floor_plan_id=target,
                    applicability=UnitApplicability.SPECIFIC_FLOOR_PLANS,
                ),
            ],
        )
        == "generalized"
    )
