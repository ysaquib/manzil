"""Pure scoped-fact selection for SCORE and rescore (DESIGN §9.3).

This module is deliberately domain-blind and LLM-free. Callers supply current
resolved Extractions/current Overrides and the concrete Floor Plan being
scored; this module applies specificity and confidence only.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from manzil_shared.models import Confidence, TargetScope, UnitApplicability

_CONFIDENCE_RANK = {
    Confidence.NOT_FOUND: 0,
    Confidence.LOW: 1,
    Confidence.MEDIUM: 2,
    Confidence.HIGH: 3,
}


@dataclass(frozen=True)
class ScopedValue:
    criterion_key: str
    value: Any
    confidence: Confidence = Confidence.HIGH
    target_scope: TargetScope = TargetScope.PROPERTY
    floor_plan_id: UUID | None = None
    applicability: UnitApplicability | None = None
    observed_at: datetime | None = None


@dataclass(frozen=True)
class ScopedOverrideValue:
    criterion_key: str
    value: Any
    target_scope: TargetScope = TargetScope.PROPERTY
    floor_plan_id: UUID | None = None
    applicability: UnitApplicability | None = None
    created_at: datetime | None = None


def meets_confidence(confidence: Confidence, minimum: Confidence) -> bool:
    return _CONFIDENCE_RANK[confidence] >= _CONFIDENCE_RANK[minimum]


def _newest(values: Iterable[ScopedValue]) -> ScopedValue | None:
    rows = list(values)
    if not rows:
        return None
    return max(
        rows, key=lambda row: row.observed_at.timestamp() if row.observed_at else float("-inf")
    )


def _newest_override(values: Iterable[ScopedOverrideValue]) -> ScopedOverrideValue | None:
    rows = list(values)
    if not rows:
        return None
    return max(
        rows, key=lambda row: row.created_at.timestamp() if row.created_at else float("-inf")
    )


def compose_presence(
    value: Any,
    applicability: UnitApplicability | None,
    *,
    boolean_claim: bool = True,
) -> Any:
    """Compose Source claim value + applicability into a scoreable unit value.

    Boolean claims use the effective presence vocabulary. Typed presence
    claims (laundry, parking, cooling) retain their exact/all-units value, but
    a generalized positive can assert only ``advertised_unconfirmed``.
    """
    if value is None:
        return None
    if value is False or value == "none":
        return "none"
    if applicability in {
        UnitApplicability.SELECT_UNITS,
        UnitApplicability.UNIT_SCOPE_UNSPECIFIED,
    }:
        return "advertised_unconfirmed"
    return "confirmed" if boolean_claim else value


def resolve_effective_value(
    *,
    criterion_key: str,
    floor_plan_id: UUID | None,
    extractions: Iterable[ScopedValue],
    overrides: Iterable[ScopedOverrideValue] = (),
    min_confidence: Confidence,
    presence_like: bool = False,
    boolean_presence: bool = True,
) -> Any:
    """Resolve one Criterion for one Floor Plan in DESIGN §9.3 order.

    Exact Override ▸ all-units Override ▸ exact resolved Extraction ▸ true
    Property/all-units/generalized resolved Extraction ▸ unknown. A latest null
    Override is a target-specific tombstone and falls through.
    """
    relevant_overrides = [row for row in overrides if row.criterion_key == criterion_key]
    exact_override = _newest_override(
        row
        for row in relevant_overrides
        if row.target_scope is TargetScope.FLOOR_PLAN and row.floor_plan_id == floor_plan_id
    )
    if exact_override is not None and exact_override.value is not None:
        return exact_override.value
    all_override = _newest_override(
        row
        for row in relevant_overrides
        if row.target_scope is TargetScope.PROPERTY
        and row.applicability is UnitApplicability.ALL_UNITS
    )
    if all_override is not None and all_override.value is not None:
        return all_override.value
    if not presence_like:
        property_override = _newest_override(
            row
            for row in relevant_overrides
            if row.target_scope is TargetScope.PROPERTY and row.applicability is None
        )
        if property_override is not None and property_override.value is not None:
            return property_override.value

    eligible = [
        row
        for row in extractions
        if row.criterion_key == criterion_key
        and row.value is not None
        and meets_confidence(row.confidence, min_confidence)
    ]
    exact = _newest(
        row
        for row in eligible
        if row.target_scope is TargetScope.FLOOR_PLAN and row.floor_plan_id == floor_plan_id
    )
    if exact is not None:
        return (
            compose_presence(
                exact.value,
                exact.applicability,
                boolean_claim=boolean_presence,
            )
            if presence_like
            else exact.value
        )

    # A true Property fact is distinct from generalized unit evidence. It is
    # still a valid effective value for every plan because its subject is the
    # Property, not because a unit association was inferred.
    if not presence_like:
        property_fact = _newest(
            row
            for row in eligible
            if row.target_scope is TargetScope.PROPERTY and row.applicability is None
        )
        if property_fact is not None:
            return property_fact.value

    for applicability in (
        UnitApplicability.ALL_UNITS,
        UnitApplicability.SELECT_UNITS,
        UnitApplicability.UNIT_SCOPE_UNSPECIFIED,
    ):
        generalized = _newest(
            row
            for row in eligible
            if row.target_scope is TargetScope.PROPERTY and row.applicability is applicability
        )
        if generalized is not None:
            return (
                compose_presence(
                    generalized.value,
                    generalized.applicability,
                    boolean_claim=boolean_presence,
                )
                if presence_like
                else generalized.value
            )
    return None


def resolve_effective_values(
    *,
    criterion_keys: Iterable[str],
    floor_plan_id: UUID | None,
    extractions: Iterable[ScopedValue],
    overrides: Iterable[ScopedOverrideValue] = (),
    min_confidence: Confidence,
    presence_like_keys: frozenset[str] = frozenset(),
    boolean_presence_keys: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    extraction_rows = list(extractions)
    override_rows = list(overrides)
    values: dict[str, Any] = {}
    for key in criterion_keys:
        value = resolve_effective_value(
            criterion_key=key,
            floor_plan_id=floor_plan_id,
            extractions=extraction_rows,
            overrides=override_rows,
            min_confidence=min_confidence,
            presence_like=key in presence_like_keys,
            boolean_presence=key in boolean_presence_keys,
        )
        if value is not None:
            values[key] = value
    return values
